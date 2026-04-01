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

    // ── OVERDRAFT ────────────────────────────────────────────────────────────
    async _loadOverdraftData() {
        try {
            const domain = this._buildDomain("date_from");
            const records = await this.orm.searchRead(
                "overdraft.interest",
                [["state", "in", ["approved"]], ...domain],
                ["overdraft_limit", "current_balance", "total_interest", "total_penalty", "bank_id"]
            );
            let totalLimit = 0, totalUsed = 0, totalInterest = 0, totalPenalty = 0;
            records.forEach(r => {
                totalLimit += r.overdraft_limit || 0;
                totalUsed += r.current_balance || 0;
                totalInterest += r.total_interest || 0;
                totalPenalty += r.total_penalty || 0;
            });
            const totalRemaining = Math.max(totalLimit - totalUsed, 0);

            // Daily/weekly interest from lines
            let dailyInterest = 0, weeklyInterest = 0;
            try {
                const lineDomain = this.state.selectedBank
                    ? [["overdraft_id.bank_id", "=", parseInt(this.state.selectedBank)]]
                    : [];
                const lines = await this.orm.searchRead(
                    "overdraft.line", lineDomain,
                    ["daily_interest", "date"]
                );
                dailyInterest = lines.length ? (lines[lines.length - 1].daily_interest || 0) : 0;
                weeklyInterest = lines.slice(-7).reduce((s, l) => s + (l.daily_interest || 0), 0);
            } catch (e) {
                console.warn("Dashboard: overdraft lines error", e);
            }

            this.state.data.overdraft = {
                totalLimit, totalUsed, totalRemaining, totalInterest, totalPenalty,
                dailyInterest, weeklyInterest,
                usedPercent: totalLimit ? Math.round((totalUsed / totalLimit) * 100) : 0,
            };
        } catch (e) {
            console.warn("Dashboard: overdraft error", e);
            this.state.data.overdraft = {
                totalLimit: 0, totalUsed: 0, totalRemaining: 0,
                totalInterest: 0, totalPenalty: 0,
                dailyInterest: 0, weeklyInterest: 0, usedPercent: 0,
            };
        }
    }

    // ── TERM LOAN ────────────────────────────────────────────────────────────
    async _loadTermLoanData() {
        try {
            const domain = this._buildDomain("start_date");
            const loans = await this.orm.searchRead(
                "term.loan",
                [["state", "in", ["active", "closed"]], ...domain],
                ["loan_amount", "loan_line_ids", "bank_id",
                    "original_total_interest", "total_interest", "start_date"]
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

            // New KPIs: Original Interest, Actual Paid, Saved Amount
            let originalInterest = 0, actualPaid = 0;
            loans.forEach(l => {
                originalInterest += l.original_total_interest || 0;
                actualPaid += l.total_interest || 0;
            });
            const savedAmount = Math.max(originalInterest - actualPaid, 0);

            // Monthly scheduled payments (existing chart)
            const monthlyMap = {};
            lines.forEach(l => {
                if (l.payment_date) {
                    const month = l.payment_date.substring(0, 7);
                    monthlyMap[month] = (monthlyMap[month] || 0) + (l.scheduled_payment || 0);
                }
            });
            const months = Object.keys(monthlyMap).sort();
            const monthlyLabels = months.slice(-12).map(m => {
                const d = new Date(m + "-01");
                return d.toLocaleString("default", { month: "short", year: "2-digit" });
            });
            const monthlyValues = months.slice(-12).map(m => monthlyMap[m]);

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
            };
        } catch (e) {
            console.warn("Dashboard: term loan error", e);
            this.state.data.term_loan = {
                totalOutstanding: 0, totalExtraPayments: 0,
                originalInterest: 0, actualPaid: 0, savedAmount: 0,
                monthlyLabels: [], monthlyValues: [],
                yearlyLabels: [], yearlyValues: [],
            };
        }
    }

    // ── MERCHANDISE LOAN ─────────────────────────────────────────────────────
    async _loadMerchandiseData() {
        try {
            const domain = this._buildDomain("date_from");
            const records = await this.orm.searchRead(
                "merchandise.loan",
                domain,
                [
                    "bank_amount", "company_amount", "outstanding_loan",
                    "goods_held_qty", "total_goods_released_qty",
                    "total_interest", "bank_coverage_percent", "company_coverage_percent",
                    "interest_per_unit", "actual_unit_cost",
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

            this.state.data.merchandise = {
                bankTotal, companyTotal, outstanding, heldQty, releasedQty,
                totalInterest, bankPercent, companyPercent, totalGoods,
            };
        } catch (e) {
            console.warn("Dashboard: merchandise error", e);
            this.state.data.merchandise = {
                bankTotal: 0, companyTotal: 0, outstanding: 0,
                heldQty: 0, releasedQty: 0, totalInterest: 0,
                bankPercent: 70, companyPercent: 30, totalGoods: 0,
            };
        }
    }

    // ── PRE-SHIPMENT LOAN ────────────────────────────────────────────────────
    async _loadPreshipmentData() {
        try {
            const domain = this._buildDomain("start_date");
            const records = await this.orm.searchRead(
                "preshipment.loan",
                [["state", "in", ["active"]], ...domain],
                [
                    "loan_amount", "loan_used", "loan_remaining",
                    "total_currency_to_store", "currency_stored", "currency_remaining",
                    "currency_fulfillment_percent", "total_interest", "penalty_amount",
                    "financed_goods_value"
                ]
            );
            let loanAmount = 0, loanUsed = 0, loanRemaining = 0,
                totalCurrency = 0, currencyStored = 0, currencyRemaining = 0,
                totalInterest = 0, totalPenalty = 0, goodsValue = 0;
            records.forEach(r => {
                loanAmount += r.loan_amount || 0;
                loanUsed += r.loan_used || 0;
                loanRemaining += r.loan_remaining || 0;
                totalCurrency += r.total_currency_to_store || 0;
                currencyStored += r.currency_stored || 0;
                currencyRemaining += r.currency_remaining || 0;
                totalInterest += r.total_interest || 0;
                totalPenalty += r.penalty_amount || 0;
                goodsValue += r.financed_goods_value || 0;
            });
            const fulfillPercent = totalCurrency
                ? Math.round((currencyStored / totalCurrency) * 100) : 0;
            const usedPercent = loanAmount
                ? Math.round((loanUsed / loanAmount) * 100) : 0;

            this.state.data.preshipment = {
                loanAmount, loanUsed, loanRemaining, totalCurrency, currencyStored,
                currencyRemaining, fulfillPercent, totalInterest, totalPenalty,
                goodsValue, usedPercent,
            };
        } catch (e) {
            console.warn("Dashboard: preshipment error", e);
            this.state.data.preshipment = {
                loanAmount: 0, loanUsed: 0, loanRemaining: 0,
                totalCurrency: 0, currencyStored: 0, currencyRemaining: 0,
                fulfillPercent: 0, totalInterest: 0, totalPenalty: 0,
                goodsValue: 0, usedPercent: 0,
            };
        }
    }

    // ── CHART RENDERING ──────────────────────────────────────────────────────
    _renderCharts() {
        Object.values(this.chartInstances).forEach(c => c && c.destroy());
        this.chartInstances = {};

        setTimeout(() => {
            try {
                if (this.state.activeTab === "overdraft") this._renderGaugeChart();
                if (this.state.activeTab === "term_loan") {
                    this._renderTermLoanChart();
                    this._renderYearlyLoanChart();
                }
                if (this.state.activeTab === "merchandise") this._renderMerchandiseChart();
                if (this.state.activeTab === "preshipment") this._renderPreshipmentChart();
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

    _fmt(val) {
        if (!val && val !== 0) return "—";
        if (val >= 1000000) return (val / 1000000).toFixed(2) + "M";
        if (val >= 1000) return (val / 1000).toFixed(1) + "K";
        return parseFloat(val).toFixed(2);
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
