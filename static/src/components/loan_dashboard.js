/** @odoo-module **/
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class LoanDashboard extends Component {
    static template = "overdraft_interest_calculator.LoanDashboard";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            activeTab: "overdraft",
            selectedBank: null,
            dateFrom: null,
            dateTo: null,
            banks: [],
            data: {
                overdraft: null,
                term_loan: null,
                merchandise: null,
                preshipment: null,
            },
            selectedOdLoans: [],
            loading: true,
            error: null,
        });
        this.chartInstances = {};

        onMounted(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.Chart = window.Chart;
            await this._loadBanks();
            await this._loadAllData();
            this._renderCharts();
        });

        onWillUnmount(() => {
            Object.values(this.chartInstances).forEach(c => c && c.destroy());
        });
    }

    async _loadBanks() {
        try {
            const banks = await this.orm.searchRead("res.bank", [], ["id", "name"]);
            this.state.banks = banks;
        } catch (e) {
            console.warn("Dashboard: failed to load banks", e);
        }
    }

    _buildDomain(dateField = "date_from") {
        const domain = [];
        if (this.state.selectedBank) {
            domain.push(["bank_id", "=", parseInt(this.state.selectedBank)]);
        }
        if (this.state.dateFrom) {
            domain.push([dateField, ">=", this.state.dateFrom]);
        }
        if (this.state.dateTo) {
            domain.push([dateField, "<=", this.state.dateTo]);
        }
        return domain;
    }

    async _loadAllData() {
        this.state.loading = true;
        this.state.error = null;
        await Promise.all([
            this._loadOverdraftData(),
            this._loadTermLoanData(),
            this._loadMerchandiseData(),
            this._loadPreshipmentData(),
        ]);
        this.state.loading = false;
    }

    // ── OVERDRAFT ───────────────────────────────────────────────────────────────────────
    async _loadOverdraftData() {
        try {
            const domain = this._buildDomain("date_from");
            const records = await this.orm.searchRead(
                "overdraft.interest",
                [["state", "in", ["approved"]], ...domain],
                ["name", "overdraft_limit", "current_balance", "current_utilization",
                 "available_balance", "interest_charged", "annual_interest_rate",
                 "total_interest", "total_penalty", "bank_id"]
            );
            let totalLimit = 0, totalUsed = 0, totalInterest = 0, totalPenalty = 0,
                totalInterestCharged = 0, totalAvailable = 0;
            records.forEach(r => {
                totalLimit += r.overdraft_limit || 0;
                totalUsed += r.current_utilization || 0;
                totalInterest += r.total_interest || 0;
                totalPenalty += r.total_penalty || 0;
                totalInterestCharged += r.interest_charged || 0;
                totalAvailable += r.available_balance || 0;
            });
            const totalRemaining = totalAvailable || Math.max(totalLimit - totalUsed, 0);

            // Daily/weekly interest from lines
            let dailyInterest = 0, weeklyInterest = 0;
            let trendDataByOd = {};
            let trendLabels = [];
            try {
                const lineDomain = this.state.selectedBank
                    ? [["overdraft_id.bank_id", "=", parseInt(this.state.selectedBank)]]
                    : [];
                const lines = await this.orm.searchRead(
                    "overdraft.line", lineDomain,
                    ["daily_interest", "date", "balance", "overdraft_id", "payment"],
                    { order: "date asc" }
                );

                // Group by overdraft
                lines.forEach(l => {
                    if (!l.overdraft_id) return;
                    const odId = l.overdraft_id[0];
                    const odName = l.overdraft_id[1];
                    if (!trendDataByOd[odId]) {
                        trendDataByOd[odId] = { name: odName, data: [] };
                    }
                    trendDataByOd[odId].data.push(l);
                });

                // Compute global daily and weekly interest
                Object.values(trendDataByOd).forEach(od => {
                    if (od.data.length) dailyInterest += od.data[od.data.length - 1].daily_interest || 0;
                    weeklyInterest += od.data.slice(-7).reduce((s, x) => s + (x.daily_interest || 0), 0);
                });

                // Extract all unique dates for common labels
                let allDates = new Set();
                lines.forEach(l => allDates.add(l.date));
                let allSortedDates = Array.from(allDates).sort();

                // Sample dates to prevent overcrowding
                const step = Math.max(1, Math.floor(allSortedDates.length / 60));
                allSortedDates.forEach((lbl, i) => {
                    if (i % step === 0 || i === allSortedDates.length - 1) {
                        trendLabels.push(lbl);
                    }
                });

                // On first load, select all ODs
                if (this.state.selectedOdLoans.length === 0) {
                    this.state.selectedOdLoans = Object.keys(trendDataByOd).map(id => parseInt(id));
                }
            } catch (e) {
                console.warn("Dashboard: overdraft lines error", e);
            }

            // ── Per-bank interest vs penalty breakdown ──
            const bankBreakdownMap = {};
            records.forEach(r => {
                const bankName = r.bank_id ? r.bank_id[1] : "Unassigned";
                if (!bankBreakdownMap[bankName]) {
                    bankBreakdownMap[bankName] = { interest: 0, penalty: 0 };
                }
                bankBreakdownMap[bankName].interest += r.total_interest || 0;
                bankBreakdownMap[bankName].penalty += r.total_penalty || 0;
            });
            const bankBreakdownLabels = Object.keys(bankBreakdownMap);
            const bankBreakdownInterest = bankBreakdownLabels.map(k => bankBreakdownMap[k].interest);
            const bankBreakdownPenalty = bankBreakdownLabels.map(k => bankBreakdownMap[k].penalty);

            // ── Monthly end-of-month balance vs payments (from all OD lines) ──
            const monthlyMap = {};
            Object.values(trendDataByOd).forEach(od => {
                // Track the last balance seen for this OD in each month
                const odMonthEndBalance = {};
                od.data.forEach(l => {
                    if (!l.date) return;
                    const monthKey = l.date.substring(0, 7); // "YYYY-MM"
                    if (!monthlyMap[monthKey]) monthlyMap[monthKey] = { balance: 0, payment: 0 };
                    monthlyMap[monthKey].payment += (l.payment || 0);
                    // Keep overwriting — last entry per month wins (data sorted asc)
                    odMonthEndBalance[monthKey] = l.balance || 0;
                });
                // Accumulate each OD's month-end utilization (abs value of negative balance)
                Object.entries(odMonthEndBalance).forEach(([monthKey, bal]) => {
                    if (monthlyMap[monthKey]) {
                        monthlyMap[monthKey].balance += Math.abs(bal);
                    }
                });
            });
            const monthlyKeys = Object.keys(monthlyMap).sort();
            const monthlyCostLabels = monthlyKeys.map(k => {
                const [y, m] = k.split("-");
                return new Date(parseInt(y), parseInt(m) - 1, 1).toLocaleString("en-US", { month: "short", year: "2-digit" });
            });
            const monthlyBalance = monthlyKeys.map(k => monthlyMap[k].balance);
            const monthlyCostPayments = monthlyKeys.map(k => monthlyMap[k].payment);

            this.state.data.overdraft = {
                totalLimit, totalUsed, totalRemaining, totalInterest, totalPenalty,
                totalInterestCharged,
                dailyInterest, weeklyInterest,
                usedPercent: totalLimit ? Math.round((totalUsed / totalLimit) * 100) : 0,
                trendLabels, trendDataByOd,
                bankBreakdownLabels, bankBreakdownInterest, bankBreakdownPenalty,
                monthlyCostLabels, monthlyBalance, monthlyCostPayments,
            };

        } catch (e) {
            console.warn("Dashboard: overdraft error", e);
            this.state.data.overdraft = {
                totalLimit: 0, totalUsed: 0, totalRemaining: 0,
                totalInterest: 0, totalPenalty: 0, totalInterestCharged: 0,
                dailyInterest: 0, weeklyInterest: 0, usedPercent: 0,
                trendLabels: [], trendBalances: [], trendInterests: [],
                bankBreakdownLabels: [], bankBreakdownInterest: [], bankBreakdownPenalty: [],
                monthlyCostLabels: [], monthlyBalance: [], monthlyCostPayments: [],
            };
        }
    }

    // ── TERM LOAN ────────────────────────────────────────────────────────────
    async _loadTermLoanData() {
        try {
            const domain = this._buildDomain("start_date");

            // Total approved: all loans formally approved regardless of
            // disbursement/schedule status (approved, active, or closed).
            const approvedLoans = await this.orm.searchRead(
                "term.loan",
                [["state", "in", ["approved", "active", "closed"]], ...domain],
                ["loan_amount"]
            );
            const totalApproved = approvedLoans.reduce((s, l) => s + (l.loan_amount || 0), 0);

            const loans = await this.orm.searchRead(
                "term.loan",
                [["state", "in", ["active", "closed"]], ...domain],
                ["name", "loan_amount", "loan_line_ids", "bank_id",
                    "original_total_interest", "total_interest", "start_date",
                    "disbursed_amount", "undisbursed_balance", "outstanding_principal",
                    "accrued_interest", "overdue_amount", "overdue_principal", "overdue_interest",
                    "due_within_30_days", "due_within_90_days",
                    "days_past_due", "is_delinquent", "alert_level", "alert_message"]
            );

            const loanIds = loans.map(l => l.id);
            const lines = loanIds.length ? await this.orm.searchRead(
                "term.loan.line",
                [["loan_id", "in", loanIds]],
                ["ending_balance", "scheduled_payment", "extra_payment", "interest", "payment_date", "loan_id"]
            ) : [];

            let totalOutstanding = 0;
            loanIds.forEach(id => {
                const loanLines = lines.filter(l => l.loan_id[0] === id);
                if (loanLines.length) {
                    totalOutstanding += loanLines[loanLines.length - 1].ending_balance || 0;
                }
            });

            const totalExtraPayments = lines.reduce((s, l) => s + (l.extra_payment || 0), 0);

            // New KPIs: disbursement, current outstanding, accrual, delinquency
            let totalDisbursed = 0, totalUndisbursed = 0, currentOutstanding = 0,
                totalAccruedInterest = 0, totalOverdue = 0, totalOverduePrincipal = 0,
                totalOverdueInterest = 0, totalDue30 = 0, totalDue90 = 0, maxDpd = 0;
            const alerts = [];
            const alertRank = { purple: 4, red: 3, yellow: 2, green: 1, none: 0 };
            loans.forEach(l => {
                totalDisbursed += l.disbursed_amount || 0;
                totalUndisbursed += l.undisbursed_balance || 0;
                currentOutstanding += l.outstanding_principal || 0;
                totalAccruedInterest += l.accrued_interest || 0;
                totalOverdue += l.overdue_amount || 0;
                totalOverduePrincipal += l.overdue_principal || 0;
                totalOverdueInterest += l.overdue_interest || 0;
                totalDue30 += l.due_within_30_days || 0;
                totalDue90 += l.due_within_90_days || 0;
                if (l.days_past_due > maxDpd) maxDpd = l.days_past_due;
                if (l.alert_level && l.alert_level !== "none") {
                    alerts.push({
                        name: l.name || l.id,
                        level: l.alert_level,
                        message: l.alert_message || "",
                        dpd: l.days_past_due || 0,
                    });
                }
            });
            alerts.sort((a, b) => alertRank[b.level] - alertRank[a.level]);

            // New KPIs: Original Interest, Actual Paid, Saved Amount
            let originalInterest = 0, actualPaid = 0;
            loans.forEach(l => {
                originalInterest += l.original_total_interest || 0;
                actualPaid += l.total_interest || 0;
            });
            const savedAmount = Math.max(originalInterest - actualPaid, 0);

            // Scheduled payments
            const paymentMap = {};
            lines.forEach(l => {
                if (l.payment_date) {
                    paymentMap[l.payment_date] = (paymentMap[l.payment_date] || 0) + (l.scheduled_payment || 0);
                }
            });
            const dates = Object.keys(paymentMap).sort();
            const monthlyLabels = dates.map(dt => {
                const [y, m, day] = dt.split("-");
                const d = new Date(parseInt(y), parseInt(m) - 1, parseInt(day));
                const monthStr = d.toLocaleString("en-US", { month: "short" }).toLowerCase();
                const yearStr = y.substring(2);
                return `${monthStr} ${parseInt(day)}/${yearStr}`;
            });
            const monthlyValues = dates.map(dt => paymentMap[dt]);

            // Yearly loan amounts (new chart)
            const yearlyMap = {};
            loans.forEach(l => {
                if (l.start_date) {
                    const year = l.start_date.substring(0, 4);
                    yearlyMap[year] = (yearlyMap[year] || 0) + (l.loan_amount || 0);
                }
            });
            const years = Object.keys(yearlyMap).sort();
            const yearlyLabels = years;
            const yearlyValues = years.map(y => yearlyMap[y]);

            this.state.data.term_loan = {
                totalOutstanding, totalExtraPayments,
                originalInterest, actualPaid, savedAmount,
                monthlyLabels, monthlyValues,
                yearlyLabels, yearlyValues,
                totalApproved,
                totalDisbursed, totalUndisbursed, currentOutstanding,
                totalAccruedInterest, totalOverdue, totalOverduePrincipal,
                totalOverdueInterest, totalDue30, totalDue90, maxDpd, alerts,
            };
        } catch (e) {
            console.warn("Dashboard: term loan error", e);
            this.state.data.term_loan = {
                totalOutstanding: 0, totalExtraPayments: 0,
                originalInterest: 0, actualPaid: 0, savedAmount: 0,
                monthlyLabels: [], monthlyValues: [],
                yearlyLabels: [], yearlyValues: [],
                totalApproved: 0,
                totalDisbursed: 0, totalUndisbursed: 0, currentOutstanding: 0,
                totalAccruedInterest: 0, totalOverdue: 0, totalOverduePrincipal: 0,
                totalOverdueInterest: 0, totalDue30: 0, totalDue90: 0, maxDpd: 0, alerts: [],
            };
        }
    }

    // ── MERCHANDISE LOAN ─────────────────────────────────────────────────────
    _categoryLabel(key) {
        const labels = {
            machinery: "Machinery",
            vehicles: "Vehicles",
            plastic_raw_materials: "Plastic Raw Materials",
            construction_materials: "Construction Materials",
            industrial_equipment: "Industrial Equipment",
            electronics: "Electronics",
            consumer_goods: "Consumer Goods",
            other: "Other",
        };
        return labels[key] || "Unspecified";
    }

    async _loadMerchandiseData() {
        try {
            const domain = this._buildDomain("date_from");
            const records = await this.orm.searchRead(
                "merchandise.loan",
                domain,
                [
                    "name", "bank_id", "state", "product_category", "sales_status",
                    "date_from", "date_to", "activation_date",
                    "bank_amount", "company_amount", "outstanding_loan", "total_goods_value",
                    "goods_held_qty", "total_goods_released_qty",
                    "total_interest", "bank_coverage_percent", "company_coverage_percent",
                    "interest_per_unit", "actual_unit_cost", "margin_per_unit",
                    "is_dead_stock_risk", "days_held",
                ]
            );
            let bankTotal = 0, companyTotal = 0, outstanding = 0,
                heldQty = 0, releasedQty = 0, totalInterest = 0;
            records.forEach(r => {
                bankTotal += r.bank_amount || 0;
                companyTotal += r.company_amount || 0;
                outstanding += r.outstanding_loan || 0;
                heldQty += r.goods_held_qty || 0;
                releasedQty += r.total_goods_released_qty || 0;
                totalInterest += r.total_interest || 0;
            });
            const totalGoods = bankTotal + companyTotal;
            const bankPercent = totalGoods ? Math.round((bankTotal / totalGoods) * 100) : 70;
            const companyPercent = 100 - bankPercent;

            // ── Exposure by product category (concentration risk) ──
            const exposureMap = {};
            records.forEach(r => {
                const key = r.product_category || "unspecified";
                if (!exposureMap[key]) {
                    exposureMap[key] = {
                        key, label: this._categoryLabel(key),
                        bankAmount: 0, outstanding: 0, count: 0,
                    };
                }
                exposureMap[key].bankAmount += r.bank_amount || 0;
                exposureMap[key].outstanding += r.outstanding_loan || 0;
                exposureMap[key].count += 1;
            });
            const exposureByCategory = Object.values(exposureMap).sort((a, b) => b.bankAmount - a.bankAmount);
            const exposureTotal = exposureByCategory.reduce((s, c) => s + c.bankAmount, 0);
            exposureByCategory.forEach(c => {
                c.percent = exposureTotal ? Math.round((c.bankAmount / exposureTotal) * 100) : 0;
            });

            // ── Loan maturity schedule by product category (active loans only) ──
            const today = new Date();
            const bucketLabels = ["Overdue", "Due ≤ 30 Days", "Due 31–90 Days", "Due > 90 Days"];
            const bucketKeys = ["overdue", "due_30", "due_90", "later"];
            const maturityMap = {};
            records.filter(r => r.state === "active" && r.date_to && r.outstanding_loan > 0).forEach(r => {
                const key = r.product_category || "unspecified";
                if (!maturityMap[key]) {
                    maturityMap[key] = {
                        key, label: this._categoryLabel(key),
                        overdue: 0, due_30: 0, due_90: 0, later: 0,
                    };
                }
                const diffDays = Math.floor((new Date(r.date_to) - today) / 86400000);
                let bucket;
                if (diffDays < 0) bucket = "overdue";
                else if (diffDays <= 30) bucket = "due_30";
                else if (diffDays <= 90) bucket = "due_90";
                else bucket = "later";
                maturityMap[key][bucket] += r.outstanding_loan || 0;
            });
            const maturityByCategory = Object.values(maturityMap).sort((a, b) =>
                (b.overdue + b.due_30) - (a.overdue + a.due_30));

            // ── Loan maturity watchlist ──
            const maturityLoans = [];
            records.filter(r => r.state === "active" && r.date_to && r.outstanding_loan > 0).forEach(r => {
                const diffDays = Math.floor((new Date(r.date_to) - today) / 86400000);
                let bucket;
                if (diffDays < 0) bucket = "overdue";
                else if (diffDays <= 30) bucket = "due30";
                else bucket = "green";
                
                maturityLoans.push({
                    name: r.name,
                    bank: r.bank_id ? r.bank_id[1] : "",
                    endDate: r.date_to,
                    daysToMaturity: diffDays,
                    outstanding: r.outstanding_loan || 0,
                    bucket: bucket
                });
            });
            maturityLoans.sort((a, b) => a.daysToMaturity - b.daysToMaturity);

            // ── Dead stock monitor ──
            const deadStockItems = records
                .filter(r => r.is_dead_stock_risk)
                .map(r => ({
                    name: r.name,
                    bank: r.bank_id ? r.bank_id[1] : "",
                    category: this._categoryLabel(r.product_category),
                    salesStatus: r.sales_status,
                    daysHeld: r.days_held || 0,
                    outstanding: r.outstanding_loan || 0,
                    goodsValue: r.total_goods_value || 0,
                }))
                .sort((a, b) => b.daysHeld - a.daysHeld);
            const deadStock = {
                count: deadStockItems.length,
                totalOutstanding: deadStockItems.reduce((s, i) => s + i.outstanding, 0),
                totalGoodsValue: deadStockItems.reduce((s, i) => s + i.goodsValue, 0),
                items: deadStockItems,
            };

            this.state.data.merchandise = {
                bankTotal, companyTotal, outstanding, heldQty, releasedQty,
                totalInterest, bankPercent, companyPercent, totalGoods,
                exposureByCategory, maturityByCategory, bucketLabels, bucketKeys,
                deadStock, maturityLoans,
            };
        } catch (e) {
            console.warn("Dashboard: merchandise error", e);
            this.state.data.merchandise = {
                bankTotal: 0, companyTotal: 0, outstanding: 0,
                heldQty: 0, releasedQty: 0, totalInterest: 0,
                bankPercent: 70, companyPercent: 30, totalGoods: 0,
                exposureByCategory: [], maturityByCategory: [], bucketLabels: [], bucketKeys: [],
                deadStock: { count: 0, totalOutstanding: 0, totalGoodsValue: 0, items: [] },
                maturityLoans: [],
            };
        }
    }

    // ── PRE-SHIPMENT LOAN ────────────────────────────────────────────────────
    async _loadPreshipmentData() {
        const empty = {
            loanAmount: 0, loanUsed: 0, loanRemaining: 0,
            totalCurrency: 0, currencyStored: 0, currencyRemaining: 0,
            fulfillPercent: 0, totalInterest: 0, totalPenalty: 0,
            goodsValue: 0, usedPercent: 0,
            expectedProceeds: 0, actualProceeds: 0, proceedsVariance: 0,
            collectionPercent: 0,
            maturityBuckets: { overdue: { count: 0, amount: 0 }, due30: { count: 0, amount: 0 },
                due60: { count: 0, amount: 0 }, due90: { count: 0, amount: 0 },
                later: { count: 0, amount: 0 } },
            maturityLoans: [],
            contractStatus: [],
        };
        try {
            const domain = this._buildDomain("start_date");
            const records = await this.orm.searchRead(
                "preshipment.loan",
                [["state", "in", ["active"]], ...domain],
                [
                    "name", "bank_id", "loan_amount", "loan_used", "loan_remaining",
                    "total_currency_to_store", "currency_stored", "currency_remaining",
                    "currency_fulfillment_percent", "total_interest", "penalty_amount",
                    "raw_material_value", "end_date", "outstanding_balance",
                    "foreign_currency_id", "sale_order_ids",
                ]
            );
            let loanAmount = 0, loanUsed = 0, loanRemaining = 0,
                totalCurrency = 0, currencyStored = 0, currencyRemaining = 0,
                totalInterest = 0, totalPenalty = 0, goodsValue = 0;
            let foreignCurrencyName = "";
            const allSaleOrderIds = new Set();
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const maturityBuckets = {
                overdue: { count: 0, amount: 0 }, due30: { count: 0, amount: 0 },
                due60: { count: 0, amount: 0 }, due90: { count: 0, amount: 0 },
                later: { count: 0, amount: 0 },
            };
            const maturityLoans = [];

            records.forEach(r => {
                loanAmount += r.loan_amount || 0;
                loanUsed += r.loan_used || 0;
                loanRemaining += r.loan_remaining || 0;
                totalCurrency += r.total_currency_to_store || 0;
                currencyStored += r.currency_stored || 0;
                currencyRemaining += r.currency_remaining || 0;
                totalInterest += r.total_interest || 0;
                totalPenalty += r.penalty_amount || 0;
                goodsValue += r.raw_material_value || 0;
                // Grab foreign currency name from the first record that has one
                if (!foreignCurrencyName && r.foreign_currency_id) {
                    foreignCurrencyName = r.foreign_currency_id[1] || "";
                }
                (r.sale_order_ids || []).forEach(id => allSaleOrderIds.add(id));

                if (r.end_date) {
                    const endDate = new Date(r.end_date);
                    endDate.setHours(0, 0, 0, 0);
                    const daysToMaturity = Math.round((endDate - today) / 86400000);
                    let bucket = "later";
                    if (daysToMaturity < 0) bucket = "overdue";
                    else if (daysToMaturity <= 30) bucket = "due30";
                    else if (daysToMaturity <= 60) bucket = "due60";
                    else if (daysToMaturity <= 90) bucket = "due90";

                    if (bucket !== "later") {
                        maturityBuckets[bucket].count += 1;
                        maturityBuckets[bucket].amount += r.outstanding_balance || 0;
                        maturityLoans.push({
                            name: r.name,
                            bank: r.bank_id ? r.bank_id[1] : "",
                            endDate: r.end_date,
                            daysToMaturity,
                            outstanding: r.outstanding_balance || 0,
                            bucket,
                        });
                    } else {
                        maturityBuckets.later.count += 1;
                        maturityBuckets.later.amount += r.outstanding_balance || 0;
                    }
                }
            });
            maturityLoans.sort((a, b) => a.daysToMaturity - b.daysToMaturity);

            const fulfillPercent = totalCurrency
                ? Math.round((currencyStored / totalCurrency) * 100) : 0;
            const usedPercent = loanAmount
                ? Math.round((loanUsed / loanAmount) * 100) : 0;

            // Expected proceeds = total foreign currency committed to bank (total_currency_to_store)
            // Actual proceeds   = foreign currency already delivered    (currency_stored)
            // Variance          = currency still outstanding            (currency_remaining)
            const expectedProceeds = totalCurrency;
            const actualProceeds = currencyStored;
            const proceedsVariance = currencyRemaining;
            const collectionPercent = totalCurrency
                ? Math.round((currencyStored / totalCurrency) * 100) : 0;

            // Linked sales orders: contract status chart only (proceeds no longer sourced here)
            let contractStatus = [];
            if (allSaleOrderIds.size) {
                try {
                    const orders = await this.orm.searchRead(
                        "sale.order",
                        [["id", "in", Array.from(allSaleOrderIds)]],
                        ["amount_total", "state", "invoice_status", "commitment_date"]
                    );
                    const buckets = {
                        pending: { label: "Pending Shipment", count: 0, amount: 0 },
                        active: { label: "Active", count: 0, amount: 0 },
                        partial: { label: "Partially Fulfilled", count: 0, amount: 0 },
                        delayed: { label: "Delayed", count: 0, amount: 0 },
                        completed: { label: "Completed", count: 0, amount: 0 },
                        cancelled: { label: "Cancelled", count: 0, amount: 0 },
                    };
                    orders.forEach(o => {
                        let key = "active";
                        if (o.state === "cancel") {
                            key = "cancelled";
                        } else if (o.state === "draft" || o.state === "sent") {
                            key = "pending";
                        } else if (o.state === "sale") {
                            const isPastCommitment = o.commitment_date
                                && new Date(o.commitment_date) < today
                                && o.invoice_status !== "invoiced";
                            if (o.invoice_status === "invoiced") {
                                key = "completed";
                            } else if (isPastCommitment) {
                                key = "delayed";
                            } else if (o.invoice_status === "to invoice") {
                                key = "partial";
                            } else {
                                key = "active";
                            }
                        }
                        buckets[key].count += 1;
                        buckets[key].amount += o.amount_total || 0;
                    });
                    contractStatus = Object.entries(buckets)
                        .map(([key, v]) => ({ key, ...v }))
                        .filter(b => b.count > 0);
                } catch (e) {
                    console.warn("Dashboard: preshipment linked sale orders error", e);
                }
            }

            this.state.data.preshipment = {
                loanAmount, loanUsed, loanRemaining, totalCurrency, currencyStored,
                currencyRemaining, fulfillPercent, totalInterest, totalPenalty,
                goodsValue, usedPercent,
                expectedProceeds, actualProceeds, proceedsVariance, collectionPercent,
                foreignCurrencyName,
                maturityBuckets, maturityLoans, contractStatus,
            };
        } catch (e) {
            console.warn("Dashboard: preshipment error", e);
            this.state.data.preshipment = empty;
        }
    }

    // ── CHART RENDERING ─────────────────────────────────────────────────────
    _renderCharts() {
        Object.values(this.chartInstances).forEach(c => c && c.destroy());
        this.chartInstances = {};

        setTimeout(() => {
            try {
                if (this.state.activeTab === "overdraft") {
                    this._renderGaugeChart();
                    this._renderOdTrendChart();
                    this._renderOdBankBreakdownChart();
                    this._renderOdMonthlyCostChart();
                }
                if (this.state.activeTab === "term_loan") {
                    this._renderTermLoanChart();
                    this._renderYearlyLoanChart();
                }
                if (this.state.activeTab === "merchandise") {
                    this._renderMerchandiseChart();
                    this._renderExposureByProductChart();
                    this._renderMaturityByProductChart();
                }
                if (this.state.activeTab === "preshipment") {
                    this._renderPreshipmentChart();
                    this._renderPreshipmentProceedsChart();
                    this._renderPreshipmentMaturityChart();
                    this._renderPreshipmentContractStatusChart();
                }
            } catch (e) {
                console.warn("Dashboard: chart render error", e);
            }
        }, 100);
    }

    _renderTermLoanChart() {
        const d = this.state.data.term_loan;
        if (!d || !d.monthlyLabels.length) return;
        const canvas = document.getElementById("termLoanBarChart");
        if (!canvas) return;
        this.chartInstances.termLoan = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.monthlyLabels,
                datasets: [{
                    label: "Scheduled Payment",
                    data: d.monthlyValues,
                    backgroundColor: "rgba(79, 140, 255, 0.75)",
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    _renderYearlyLoanChart() {
        const d = this.state.data.term_loan;
        if (!d || !d.yearlyLabels.length) return;
        const canvas = document.getElementById("yearlyLoanBarChart");
        if (!canvas) return;
        this.chartInstances.yearlyLoan = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.yearlyLabels,
                datasets: [{
                    label: "Loan Amount",
                    data: d.yearlyValues,
                    backgroundColor: "rgba(99, 102, 241, 0.75)",
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    toggleOdLoan(odId, checked) {
        odId = parseInt(odId);
        if (checked) {
            if (!this.state.selectedOdLoans.includes(odId)) {
                this.state.selectedOdLoans.push(odId);
            }
        } else {
            this.state.selectedOdLoans = this.state.selectedOdLoans.filter(id => id !== odId);
        }
        this._renderOdTrendChart();
    }

    toggleAllOdLoans(checked) {
        if (checked && this.state.data.overdraft) {
            this.state.selectedOdLoans = Object.keys(this.state.data.overdraft.trendDataByOd).map(id => parseInt(id));
        } else {
            this.state.selectedOdLoans = [];
        }
        this._renderOdTrendChart();
    }

    isOdSelected(odId) {
        return this.state.selectedOdLoans.includes(parseInt(odId, 10));
    }

    _renderGaugeChart() {
        const d = this.state.data.overdraft;
        if (!d) return;
        const canvas = document.getElementById("overdraftGaugeChart");
        if (!canvas) return;
        this.chartInstances.gauge = new this.Chart(canvas, {
            type: "doughnut",
            data: {
                labels: ["Used", "Remaining"],
                datasets: [{
                    data: [d.totalUsed || 0.001, Math.max(d.totalRemaining, 0.001)],
                    backgroundColor: ["#ef4444", "#22c55e"],
                    borderWidth: 0,
                    circumference: 180,
                    rotation: 270,
                }],
            },
            options: {
                responsive: true,
                cutout: "70%",
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (c) => this._fmt(c.raw) } },
                },
            },
        });
    }

    _renderOdTrendChart() {
        const d = this.state.data.overdraft;
        if (!d || !d.trendDataByOd) return;
        const canvas = document.getElementById("odDailyTrendChart");
        if (!canvas) return;

        if (this.chartInstances.odTrend) {
            this.chartInstances.odTrend.destroy();
            this.chartInstances.odTrend = null;
        }

        // Only include selected loans
        const selectedOdKeys = Object.keys(d.trendDataByOd).filter(k => this.state.selectedOdLoans.includes(parseInt(k)));
        
        // Dynamically compute common labels based only on selected loans
        let activeDates = new Set();
        selectedOdKeys.forEach(k => {
            d.trendDataByOd[k].data.forEach(l => activeDates.add(l.date));
        });
        let activeSortedDates = Array.from(activeDates).sort();

        // Sample if necessary
        const step = Math.max(1, Math.floor(activeSortedDates.length / 60));
        let activeLabels = [];
        activeSortedDates.forEach((lbl, i) => {
            if (i % step === 0 || i === activeSortedDates.length - 1) {
                activeLabels.push(lbl);
            }
        });

        // Format labels as short dates
        const labels = activeLabels.map(dt => {
            const [y, m, day] = dt.split("-");
            return `${parseInt(day)}/${parseInt(m)}`;
        });

        const datasets = [];
        const colors = ["#ef4444", "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4"];
        let colorIdx = 0;

        selectedOdKeys.forEach(odId => {
            const od = d.trendDataByOd[odId];
            const color = colors[colorIdx % colors.length];
            colorIdx++;

            let balanceData = [];
            let interestData = [];
            
            activeLabels.forEach(lbl => {
                const line = od.data.find(l => l.date === lbl);
                balanceData.push(line ? (line.balance || 0) : null);
                interestData.push(line ? (line.daily_interest || 0) : null);
            });

            // Balance Dataset (Smooth Area)
            datasets.push({
                label: od.name + " Balance",
                data: balanceData,
                backgroundColor: color + "33", // 20% opacity for the area fill
                borderColor: color,
                borderWidth: 2,
                fill: true,
                tension: 0.4, // Smooth curve
                pointRadius: 0, // Hide points for clean look
                pointHitRadius: 10,
                pointHoverRadius: 5,
                spanGaps: true,
                yAxisID: "yBalance",
            });
            // Interest Dataset (Dashed Line)
            datasets.push({
                label: od.name + " Daily Interest",
                data: interestData,
                backgroundColor: "transparent",
                borderColor: color,
                borderWidth: 2,
                borderDash: [5, 5], // Distinct dashed pattern
                fill: false,
                tension: 0.4, // Smooth curve
                pointRadius: 0,
                pointHitRadius: 10,
                pointHoverRadius: 5,
                spanGaps: true,
                yAxisID: "yInterest",
            });
        });

        this.chartInstances.odTrend = new this.Chart(canvas, {
            type: "line",
            data: { labels, datasets },
            options: {
                responsive: true,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "right" },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${this._fmt(c.raw)}`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false }, // Remove vertical grid lines for cleaner look
                    },
                    yBalance: {
                        type: "linear",
                        position: "left",
                        ticks: { callback: v => this._fmt(v) },
                        title: { display: true, text: "Balance" },
                    },
                    yInterest: {
                        type: "linear",
                        position: "right",
                        grid: { drawOnChartArea: false },
                        ticks: { callback: v => this._fmt(v) },
                        title: { display: true, text: "Daily Interest" },
                    },
                },
            },
        });
    }

    _renderOdBankBreakdownChart() {
        const d = this.state.data.overdraft;
        if (!d || !d.bankBreakdownLabels || !d.bankBreakdownLabels.length) return;
        const canvas = document.getElementById("odBankBreakdownChart");
        if (!canvas) return;
        if (this.chartInstances.odBankBreakdown) {
            this.chartInstances.odBankBreakdown.destroy();
            this.chartInstances.odBankBreakdown = null;
        }
        this.chartInstances.odBankBreakdown = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.bankBreakdownLabels,
                datasets: [
                    {
                        label: "Interest",
                        data: d.bankBreakdownInterest,
                        backgroundColor: "rgba(239, 68, 68, 0.8)",
                        borderRadius: 6,
                        borderSkipped: false,
                    },
                    {
                        label: "Penalty",
                        data: d.bankBreakdownPenalty,
                        backgroundColor: "rgba(245, 158, 11, 0.8)",
                        borderRadius: 6,
                        borderSkipped: false,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${this._fmt(c.raw)}`,
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        beginAtZero: true,
                        ticks: { callback: v => this._fmt(v) },
                        title: { display: true, text: "Amount" },
                    },
                },
            },
        });
    }

    _renderOdMonthlyCostChart() {
        const d = this.state.data.overdraft;
        if (!d || !d.monthlyCostLabels || !d.monthlyCostLabels.length) return;
        const canvas = document.getElementById("odMonthlyCostChart");
        if (!canvas) return;
        if (this.chartInstances.odMonthlyCost) {
            this.chartInstances.odMonthlyCost.destroy();
            this.chartInstances.odMonthlyCost = null;
        }
        this.chartInstances.odMonthlyCost = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.monthlyCostLabels,
                datasets: [
                    {
                        label: "Month-End Balance (Drawn)",
                        data: d.monthlyBalance,
                        backgroundColor: "rgba(239, 68, 68, 0.7)",
                        borderRadius: 4,
                        order: 2,
                        yAxisID: "yBalance",
                    },
                    {
                        label: "Payments Made",
                        data: d.monthlyCostPayments,
                        type: "line",
                        borderColor: "#10b981",
                        backgroundColor: "rgba(16, 185, 129, 0.15)",
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointHoverRadius: 7,
                        order: 1,
                        yAxisID: "yPayments",
                    },
                ],
            },
            options: {
                responsive: true,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${this._fmt(c.raw)}`,
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false } },
                    yBalance: {
                        type: "linear",
                        position: "left",
                        beginAtZero: true,
                        ticks: { callback: v => this._fmt(v) },
                        title: { display: true, text: "Balance Drawn" },
                        grid: { color: "rgba(0,0,0,0.05)" },
                    },
                    yPayments: {
                        type: "linear",
                        position: "right",
                        beginAtZero: true,
                        ticks: { callback: v => this._fmt(v) },
                        title: { display: true, text: "Payments" },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        });
    }

    _renderMerchandiseChart() {
        const d = this.state.data.merchandise;
        if (!d) return;
        const canvas = document.getElementById("merchandisePieChart");
        if (!canvas) return;
        this.chartInstances.merchandise = new this.Chart(canvas, {
            type: "doughnut",
            data: {
                labels: [`Bank (${d.bankPercent}%)`, `Company (${d.companyPercent}%)`],
                datasets: [{
                    data: [d.bankTotal || 0.001, d.companyTotal || 0.001],
                    backgroundColor: ["#6366f1", "#f59e0b"],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (c) => this._fmt(c.raw) } },
                },
            },
        });
    }

    _renderExposureByProductChart() {
        const d = this.state.data.merchandise;
        if (!d || !d.exposureByCategory || !d.exposureByCategory.length) return;
        const canvas = document.getElementById("merchandiseExposureChart");
        if (!canvas) return;
        this.chartInstances.exposure = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.exposureByCategory.map(c => c.label),
                datasets: [{
                    label: "Bank Exposure",
                    data: d.exposureByCategory.map(c => c.bankAmount),
                    backgroundColor: "rgba(99, 102, 241, 0.75)",
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                indexAxis: "y",
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (c) => this._fmt(c.raw) } },
                },
                scales: { x: { ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    _renderMaturityByProductChart() {
        const d = this.state.data.merchandise;
        if (!d || !d.maturityByCategory || !d.maturityByCategory.length) return;
        const canvas = document.getElementById("merchandiseMaturityChart");
        if (!canvas) return;
        const colors = { overdue: "#ef4444", due_30: "#f59e0b", due_90: "#3b82f6", later: "#22c55e" };
        const datasets = d.bucketKeys.map((key, i) => ({
            label: d.bucketLabels[i],
            data: d.maturityByCategory.map(c => c[key] || 0),
            backgroundColor: colors[key],
        }));
        this.chartInstances.maturity = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: d.maturityByCategory.map(c => c.label),
                datasets,
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${this._fmt(c.raw)}` } },
                },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, ticks: { callback: v => this._fmt(v) } },
                },
            },
        });
    }

    _renderPreshipmentChart() {
        const d = this.state.data.preshipment;
        if (!d) return;
        const canvas = document.getElementById("preshipmentProgressChart");
        if (!canvas) return;
        this.chartInstances.preshipment = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: ["Loan Used", "Loan Remaining"],
                datasets: [{
                    data: [d.loanUsed, d.loanRemaining],
                    backgroundColor: ["#10b981", "#e5e7eb"],
                    borderRadius: 8,
                }],
            },
            options: {
                responsive: true,
                indexAxis: "y",
                plugins: { legend: { display: false } },
                scales: { x: { stacked: false, ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    _renderPreshipmentProceedsChart() {
        const d = this.state.data.preshipment;
        if (!d) return;
        const canvas = document.getElementById("preshipmentProceedsChart");
        if (!canvas) return;
        this.chartInstances.preshipmentProceeds = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: ["Export Proceeds"],
                datasets: [
                    {
                        label: "Expected",
                        data: [d.expectedProceeds],
                        backgroundColor: "#94a3b8",
                        borderRadius: 6,
                    },
                    {
                        label: "Actual Received",
                        data: [d.actualProceeds],
                        backgroundColor: "#10b981",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                indexAxis: "y",
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${this._fmt(c.raw)}` } },
                },
                scales: { x: { ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    _renderPreshipmentMaturityChart() {
        const d = this.state.data.preshipment;
        if (!d || !d.maturityBuckets) return;
        const canvas = document.getElementById("preshipmentMaturityChart");
        if (!canvas) return;
        const b = d.maturityBuckets;
        this.chartInstances.preshipmentMaturity = new this.Chart(canvas, {
            type: "bar",
            data: {
                labels: ["Overdue", "0–30 Days", "31–60 Days", "61–90 Days"],
                datasets: [{
                    label: "Outstanding Balance",
                    data: [b.overdue.amount, b.due30.amount, b.due60.amount, b.due90.amount],
                    backgroundColor: ["#ef4444", "#f59e0b", "#3b82f6", "#22c55e"],
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (c) => this._fmt(c.raw) } },
                },
                scales: { y: { ticks: { callback: v => this._fmt(v) } } },
            },
        });
    }

    _renderPreshipmentContractStatusChart() {
        const d = this.state.data.preshipment;
        if (!d || !d.contractStatus || !d.contractStatus.length) return;
        const canvas = document.getElementById("preshipmentContractStatusChart");
        if (!canvas) return;
        const colors = {
            pending: "#94a3b8", active: "#3b82f6", partial: "#f59e0b",
            delayed: "#ef4444", completed: "#22c55e", cancelled: "#64748b",
        };
        this.chartInstances.preshipmentContractStatus = new this.Chart(canvas, {
            type: "doughnut",
            data: {
                labels: d.contractStatus.map(s => `${s.label} (${s.count})`),
                datasets: [{
                    data: d.contractStatus.map(s => s.amount),
                    backgroundColor: d.contractStatus.map(s => colors[s.key] || "#94a3b8"),
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { callbacks: { label: (c) => this._fmt(c.raw) } },
                },
            },
        });
    }

    _fmt(val) {
        if (!val && val !== 0) return "—";
        if (val >= 1000000) return (val / 1000000).toFixed(2) + "M";
        if (val >= 1000) return (val / 1000).toFixed(1) + "K";
        return parseFloat(val).toFixed(2);
    }

    _fmtFx(val, currencyName) {
        const num = this._fmt(val);
        if (num === "—") return "—";
        return currencyName ? `${num} ${currencyName}` : num;
    }

    _alertLabel(level) {
        return {
            green: "Green — Approaching Due",
            yellow: "Yellow — Delinquent",
            red: "Red — High Risk",
            purple: "Purple — Impaired",
        }[level] || level;
    }

    async setTab(tab) {
        this.state.activeTab = tab;
        await this._loadAllData();
        this._renderCharts();
    }

    async applyFilters(ev) {
        ev.preventDefault();
        await this._loadAllData();
        this._renderCharts();
    }

    onBankChange(ev) {
        this.state.selectedBank = ev.target.value || null;
    }
    onDateFromChange(ev) { this.state.dateFrom = ev.target.value || null; }
    onDateToChange(ev) { this.state.dateTo = ev.target.value || null; }
}

registry.category("actions").add("loan_management_dashboard", LoanDashboard);