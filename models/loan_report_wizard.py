import io
import html as html_mod
import base64
import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ─── Shared HTML styles ───────────────────────────────────────────────────────
_TABLE_STYLE = """
<style>
    .loan-report-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', Roboto, Arial, sans-serif;
        font-size: 13px;
        margin-bottom: 24px;
    }
    .loan-report-table caption {
        caption-side: top;
        text-align: left;
        font-size: 16px;
        font-weight: 700;
        color: #333;
        padding: 10px 0 6px;
        border-bottom: 3px solid #714b67;
        margin-bottom: 0;
    }
    .loan-report-table thead th {
        background-color: #714b67;
        color: #ffffff;
        padding: 10px 12px;
        text-align: left;
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border: 1px solid #5d3e56;
    }
    .loan-report-table tbody td {
        padding: 8px 12px;
        border: 1px solid #e0e0e0;
        color: #333;
    }
    .loan-report-table tbody tr:nth-child(even) {
        background-color: #f9f5f8;
    }
    .loan-report-table tbody tr:hover {
        background-color: #f0e8ee;
    }
    .loan-report-table tfoot td {
        padding: 10px 12px;
        font-weight: 700;
        background-color: #f3edf1;
        border: 1px solid #d4c4d0;
        color: #714b67;
    }
    .loan-report-table .text-right {
        text-align: right;
    }
    .loan-report-table .text-center {
        text-align: center;
    }
    .report-summary-box {
        background: linear-gradient(135deg, #714b67 0%, #8e6585 100%);
        color: #fff;
        padding: 16px 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 14px;
    }
    .report-summary-box strong { color: #fde8f5; }
    .report-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: capitalize;
    }
    .badge-draft { background: #e0e0e0; color: #555; }
    .badge-submitted { background: #fff3cd; color: #856404; }
    .badge-approved { background: #d4edda; color: #155724; }
    .badge-active { background: #cce5ff; color: #004085; }
    .badge-closed { background: #d6d8db; color: #383d41; }
    .badge-rejected { background: #f8d7da; color: #721c24; }
    .maturity-urgent { background: #f8d7da; color: #721c24; font-weight: 600; }
    .maturity-warning { background: #fff3cd; color: #856404; }
    .maturity-info { background: #d1ecf1; color: #0c5460; }
</style>
"""


def _fmt(value, decimals=2):
    """Format a numeric value with thousands separators."""
    if value is None:
        return '0.00'
    return f'{value:,.{decimals}f}'


def _state_badge(state):
    """Render a state value as a styled badge."""
    css_class = f'badge-{state}' if state else 'badge-draft'
    label = (state or 'draft').replace('_', ' ').title()
    return f'<span class="report-badge {css_class}">{label}</span>'


class LoanReportWizard(models.TransientModel):
    _name = 'loan.report.wizard'
    _description = 'Loan Report Wizard'

    # ─── Fields ───────────────────────────────────────────────────────────────
    report_type = fields.Selection([
        ('portfolio', 'Loan Portfolio Report'),
        ('repayment', 'Repayment Schedule Report'),
        ('utilization', 'Loan Utilization Report'),
        ('maturity', 'Loan Maturity Report'),
        ('exposure', 'Loan Exposure Report'),
    ], string='Report Type', required=True, default='portfolio')

    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    bank_id = fields.Many2one(
        'res.bank',
        string='Bank',
        help='Filter by a specific bank. Leave empty to include ALL banks.',
    )
    state_filter = fields.Selection([
        ('all', 'All Statuses'),
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
    ], string='Status Filter', default='all')

    maturity_window = fields.Selection([
        ('30', '30 Days'),
        ('60', '60 Days'),
        ('90', '90 Days'),
    ], string='Maturity Window', default='30',
       help='Show loans maturing within this many days')

    group_by = fields.Selection([
        ('bank', 'By Bank'),
        ('business_unit', 'By Business Unit'),
        ('state', 'By Status'),
    ], string='Group By', default='bank',
       help='Dimension for exposure grouping')

    report_html = fields.Html(
        string='Report Output',
        sanitize=False,
        readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
    ], default='draft')

    # ─── Auto-open (called from server actions in menu) ───────────────────────
    @api.model
    def action_open_report(self, report_type):
        """Create wizard pre-set to the current month (all banks) and
        immediately generate the report, then return the form view."""
        today = fields.Date.context_today(self)
        date_from = today.replace(day=1)
        record = self.create({
            'report_type': report_type,
            'date_from': date_from,
            'date_to': today,
            # bank_id is left empty → all banks are included
        })
        # Auto-generate so the user sees results immediately
        record._do_generate()
        return {
            'type': 'ir.actions.act_window',
            'name': dict(self._fields['report_type'].selection).get(report_type, 'Report'),
            'res_model': self._name,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ─── Generate ─────────────────────────────────────────────────────────────
    def _do_generate(self):
        """Internal: run the generator and write HTML + state. No return value."""
        self.ensure_one()
        generators = {
            'portfolio': self._generate_portfolio_report,
            'repayment': self._generate_repayment_report,
            'utilization': self._generate_utilization_report,
            'maturity': self._generate_maturity_report,
            'exposure': self._generate_exposure_report,
        }
        generator = generators.get(self.report_type)
        if not generator:
            raise UserError(_('Unknown report type: %s') % self.report_type)
        html = generator()
        self.write({
            'report_html': _TABLE_STYLE + html,
            'state': 'generated',
        })

    def action_generate(self):
        """Button handler — regenerate and stay on the same form view."""
        self._do_generate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ═════════════════════════════════════════════════════════════════════════
    # HELPER — Collect all loans from all 4 models as unified dicts
    # ═════════════════════════════════════════════════════════════════════════
    def _collect_all_loans(self):
        """Return a list of dicts with normalised field names across all
        four loan models, plus a 'record' key holding the real record."""
        loans = []

        # ── Overdraft ─────────────────────────────────────────────────────
        domain_od = self._base_domain_overdraft()
        for r in self.env['overdraft.interest'].search(domain_od):
            loans.append({
                'record': r,
                'name': html_mod.escape(r.name or ''),
                'loan_type': 'Overdraft',
                'bank_name': html_mod.escape(r.bank_id.name or ''),
                'approved': r.overdraft_limit,
                'outstanding': r.current_utilization,
                'utilized': r.current_utilization,
                'remaining': r.available_balance,
                'interest_rate': r.annual_interest_rate,
                'maturity_date': r.date_to,
                'state': r.state,
                'currency': r.currency_id,
            })

        # ── Term Loan ─────────────────────────────────────────────────────
        domain_tl = self._base_domain_term_loan()
        for r in self.env['term.loan'].search(domain_tl):
            # Compute maturity date from schedule lines
            lines = r.loan_line_ids.sorted('payment_number')
            maturity = lines[-1].payment_date if lines else r.start_date
            loans.append({
                'record': r,
                'name': html_mod.escape(r.name or ''),
                'loan_type': 'Term Loan',
                'bank_name': html_mod.escape(r.bank_id.name or ''),
                'approved': r.loan_amount,
                'outstanding': r.outstanding_principal,
                'utilized': r.disbursed_amount,
                'remaining': r.undisbursed_balance,
                'interest_rate': r.annual_interest_rate,
                'maturity_date': maturity,
                'state': r.state,
                'currency': r.currency_id,
            })

        # ── Merchandise Loan ──────────────────────────────────────────────
        domain_ml = self._base_domain_merchandise()
        for r in self.env['merchandise.loan'].search(domain_ml):
            # If the loan is given (submitted, approved, active, closed), full bank share (bank_amount) is disbursed/utilized
            is_given = r.state in ('submitted', 'approved', 'active', 'closed')
            utilized = r.bank_amount if is_given else 0.0
            remaining = max(r.bank_amount - utilized, 0.0)
            loans.append({
                'record': r,
                'name': html_mod.escape(r.name or ''),
                'loan_type': 'Merchandise Loan',
                'bank_name': html_mod.escape(r.bank_id.name or ''),
                'approved': r.bank_amount,
                'outstanding': r.outstanding_loan,
                'utilized': utilized,
                'remaining': remaining,
                'interest_rate': r.annual_interest_rate,
                'maturity_date': r.date_to,
                'state': r.state,
                'currency': r.currency_id,
            })

        # ── Pre-Shipment Loan ─────────────────────────────────────────────
        domain_ps = self._base_domain_preshipment()
        for r in self.env['preshipment.loan'].search(domain_ps):
            loans.append({
                'record': r,
                'name': html_mod.escape(r.name or ''),
                'loan_type': 'Pre-Shipment',
                'bank_name': html_mod.escape(r.bank_id.name or ''),
                'approved': r.loan_amount,
                'outstanding': r.outstanding_balance,
                'utilized': r.loan_used,
                'remaining': r.loan_remaining,
                'interest_rate': r.annual_interest_rate,
                'maturity_date': r.end_date,
                'state': r.state,
                'currency': r.currency_id,
            })

        return loans

    # ─── Domain builders ──────────────────────────────────────────────────
    def _base_domain_overdraft(self):
        domain = []
        if self.bank_id:
            domain.append(('bank_id', '=', self.bank_id.id))
        if self.state_filter and self.state_filter != 'all':
            domain.append(('state', '=', self.state_filter))
        return domain

    def _base_domain_term_loan(self):
        domain = []
        if self.bank_id:
            domain.append(('bank_id', '=', self.bank_id.id))
        if self.state_filter and self.state_filter != 'all':
            domain.append(('state', '=', self.state_filter))
        return domain

    def _base_domain_merchandise(self):
        domain = []
        if self.bank_id:
            domain.append(('bank_id', '=', self.bank_id.id))
        if self.state_filter and self.state_filter != 'all':
            domain.append(('state', '=', self.state_filter))
        return domain

    def _base_domain_preshipment(self):
        domain = []
        if self.bank_id:
            domain.append(('bank_id', '=', self.bank_id.id))
        if self.state_filter and self.state_filter != 'all':
            domain.append(('state', '=', self.state_filter))
        return domain

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT 1 — Loan Portfolio
    # ═════════════════════════════════════════════════════════════════════════
    def _generate_portfolio_report(self):
        loans = self._collect_all_loans()
        if not loans:
            return '<p style="padding:20px;color:#888;">No loan records found matching the selected filters.</p>'

        total_approved = sum(l['approved'] for l in loans)
        total_outstanding = sum(l['outstanding'] for l in loans)

        html = f"""
        <div class="report-summary-box">
            <strong>Loan Portfolio Summary</strong> &mdash;
            Total Facilities: <strong>{len(loans)}</strong> |
            Total Approved: <strong>{_fmt(total_approved)}</strong> |
            Total Outstanding: <strong>{_fmt(total_outstanding)}</strong>
        </div>
        <table class="loan-report-table">
            <caption>Loan Portfolio Report</caption>
            <thead>
                <tr>
                    <th>Loan ID</th>
                    <th>Loan Type</th>
                    <th>Bank</th>
                    <th class="text-right">Approved Amount</th>
                    <th class="text-right">Outstanding Balance</th>
                    <th class="text-right">Interest Rate (%)</th>
                    <th class="text-center">Maturity Date</th>
                    <th class="text-center">Status</th>
                </tr>
            </thead>
            <tbody>
        """
        for l in loans:
            maturity_str = str(l['maturity_date']) if l['maturity_date'] else '—'
            html += f"""
                <tr>
                    <td>{l['name']}</td>
                    <td>{l['loan_type']}</td>
                    <td>{l['bank_name']}</td>
                    <td class="text-right">{_fmt(l['approved'])}</td>
                    <td class="text-right">{_fmt(l['outstanding'])}</td>
                    <td class="text-right">{_fmt(l['interest_rate'], 4)}</td>
                    <td class="text-center">{maturity_str}</td>
                    <td class="text-center">{_state_badge(l['state'])}</td>
                </tr>
            """

        html += f"""
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="3"><strong>Grand Total</strong></td>
                    <td class="text-right">{_fmt(total_approved)}</td>
                    <td class="text-right">{_fmt(total_outstanding)}</td>
                    <td colspan="3"></td>
                </tr>
            </tfoot>
        </table>
        """
        return html

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT 2 — Repayment Schedule (Term Loans)
    # ═════════════════════════════════════════════════════════════════════════
    def _generate_repayment_report(self):
        domain = self._base_domain_term_loan()
        term_loans = self.env['term.loan'].search(domain)
        if not term_loans:
            return '<p style="padding:20px;color:#888;">No term loan records found matching the selected filters.</p>'

        html = ''
        for loan in term_loans:
            lines = loan.loan_line_ids.sorted('payment_number')
            if not lines:
                continue

            # Apply date filters on line payment dates
            filtered_lines = lines
            if self.date_from:
                filtered_lines = filtered_lines.filtered(
                    lambda l: l.payment_date and l.payment_date >= self.date_from
                )
            if self.date_to:
                filtered_lines = filtered_lines.filtered(
                    lambda l: l.payment_date and l.payment_date <= self.date_to
                )
            if not filtered_lines:
                continue

            total_principal = sum(l.principal for l in filtered_lines)
            total_interest = sum(l.interest for l in filtered_lines)
            total_payment = sum(l.total_payment for l in filtered_lines)

            html += f"""
            <table class="loan-report-table">
                <caption>{loan.name} — {loan.bank_id.name or 'N/A'}
                    (Amount: {_fmt(loan.loan_amount)} | Rate: {_fmt(loan.annual_interest_rate, 4)})</caption>
                <thead>
                    <tr>
                        <th class="text-center">Pmt #</th>
                        <th class="text-center">Due Date</th>
                        <th class="text-right">Principal</th>
                        <th class="text-right">Interest</th>
                        <th class="text-right">Installment Amount</th>
                        <th class="text-right">Extra Payment</th>
                        <th class="text-right">Ending Balance</th>
                        <th class="text-center">Status</th>
                    </tr>
                </thead>
                <tbody>
            """
            for line in filtered_lines:
                paid_badge = ('<span class="report-badge badge-approved">Paid</span>'
                              if line.is_paid else
                              '<span class="report-badge badge-draft">Pending</span>')
                if not line.is_paid and line.is_overdue:
                    paid_badge = '<span class="report-badge badge-rejected">Overdue</span>'

                html += f"""
                    <tr>
                        <td class="text-center">{line.payment_number}</td>
                        <td class="text-center">{line.payment_date or '—'}</td>
                        <td class="text-right">{_fmt(line.principal)}</td>
                        <td class="text-right">{_fmt(line.interest)}</td>
                        <td class="text-right">{_fmt(line.total_payment)}</td>
                        <td class="text-right">{_fmt(line.extra_payment)}</td>
                        <td class="text-right">{_fmt(line.ending_balance)}</td>
                        <td class="text-center">{paid_badge}</td>
                    </tr>
                """

            html += f"""
                </tbody>
                <tfoot>
                    <tr>
                        <td colspan="2"><strong>Total</strong></td>
                        <td class="text-right">{_fmt(total_principal)}</td>
                        <td class="text-right">{_fmt(total_interest)}</td>
                        <td class="text-right">{_fmt(total_payment)}</td>
                        <td colspan="3"></td>
                    </tr>
                </tfoot>
            </table>
            """

        if not html:
            return '<p style="padding:20px;color:#888;">No repayment schedule lines found for the selected filters.</p>'
        return html

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT 3 — Loan Utilization
    # ═════════════════════════════════════════════════════════════════════════
    def _generate_utilization_report(self):
        loans = self._collect_all_loans()
        if not loans:
            return '<p style="padding:20px;color:#888;">No loan records found matching the selected filters.</p>'

        total_approved = sum(l['approved'] for l in loans)
        total_utilized = sum(l['utilized'] for l in loans)
        total_remaining = sum(l['remaining'] for l in loans)
        overall_pct = (total_utilized / total_approved * 100) if total_approved else 0

        html = f"""
        <div class="report-summary-box">
            <strong>Utilization Summary</strong> &mdash;
            Total Approved: <strong>{_fmt(total_approved)}</strong> |
            Total Utilized: <strong>{_fmt(total_utilized)}</strong> |
            Overall Utilization: <strong>{_fmt(overall_pct, 1)}%</strong>
        </div>
        <table class="loan-report-table">
            <caption>Loan Utilization Report</caption>
            <thead>
                <tr>
                    <th>Loan ID</th>
                    <th>Loan Type</th>
                    <th>Bank</th>
                    <th class="text-right">Approved Amount</th>
                    <th class="text-right">Utilized / Disbursed</th>
                    <th class="text-right">Remaining Available</th>
                    <th class="text-right">Utilization %</th>
                    <th class="text-center">Status</th>
                </tr>
            </thead>
            <tbody>
        """
        for l in loans:
            pct = (l['utilized'] / l['approved'] * 100) if l['approved'] else 0
            pct_color = '#155724' if pct < 75 else ('#856404' if pct < 90 else '#721c24')
            html += f"""
                <tr>
                    <td>{l['name']}</td>
                    <td>{l['loan_type']}</td>
                    <td>{l['bank_name']}</td>
                    <td class="text-right">{_fmt(l['approved'])}</td>
                    <td class="text-right">{_fmt(l['utilized'])}</td>
                    <td class="text-right">{_fmt(l['remaining'])}</td>
                    <td class="text-right" style="color:{pct_color};font-weight:600;">{_fmt(pct, 1)}%</td>
                    <td class="text-center">{_state_badge(l['state'])}</td>
                </tr>
            """

        html += f"""
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="3"><strong>Grand Total</strong></td>
                    <td class="text-right">{_fmt(total_approved)}</td>
                    <td class="text-right">{_fmt(total_utilized)}</td>
                    <td class="text-right">{_fmt(total_remaining)}</td>
                    <td class="text-right" style="font-weight:700;">{_fmt(overall_pct, 1)}%</td>
                    <td></td>
                </tr>
            </tfoot>
        </table>
        """
        return html

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT 4 — Loan Maturity
    # ═════════════════════════════════════════════════════════════════════════
    def _generate_maturity_report(self):
        window_days = int(self.maturity_window or '30')
        today = fields.Date.context_today(self)
        cutoff = today + timedelta(days=window_days)

        loans = self._collect_all_loans()
        # Filter to loans maturing within window
        maturing = [
            l for l in loans
            if l['maturity_date'] and today <= l['maturity_date'] <= cutoff
        ]

        if not maturing:
            return (f'<p style="padding:20px;color:#888;">No loans maturing within '
                    f'the next {window_days} days.</p>')

        # Sort by maturity date
        maturing.sort(key=lambda l: l['maturity_date'])

        # Bucket counts
        b30 = [l for l in maturing if (l['maturity_date'] - today).days <= 30]
        b60 = [l for l in maturing if 30 < (l['maturity_date'] - today).days <= 60]
        b90 = [l for l in maturing if 60 < (l['maturity_date'] - today).days <= 90]

        total_outstanding = sum(l['outstanding'] for l in maturing)

        html = f"""
        <div class="report-summary-box">
            <strong>Maturity Report</strong> (next {window_days} days) &mdash;
            Maturing Loans: <strong>{len(maturing)}</strong> |
            Total Outstanding: <strong>{_fmt(total_outstanding)}</strong><br/>
            Within 30 days: <strong>{len(b30)}</strong> |
            31-60 days: <strong>{len(b60)}</strong> |
            61-90 days: <strong>{len(b90)}</strong>
        </div>
        <table class="loan-report-table">
            <caption>Loan Maturity Report — Loans Maturing Within {window_days} Days</caption>
            <thead>
                <tr>
                    <th>Loan ID</th>
                    <th>Loan Type</th>
                    <th>Bank</th>
                    <th class="text-center">Maturity Date</th>
                    <th class="text-center">Days Until Maturity</th>
                    <th class="text-right">Outstanding Balance</th>
                    <th class="text-center">Urgency</th>
                    <th class="text-center">Status</th>
                </tr>
            </thead>
            <tbody>
        """
        for l in maturing:
            days_left = (l['maturity_date'] - today).days
            if days_left <= 30:
                urgency_class = 'maturity-urgent'
                urgency_label = 'Urgent'
            elif days_left <= 60:
                urgency_class = 'maturity-warning'
                urgency_label = 'Warning'
            else:
                urgency_class = 'maturity-info'
                urgency_label = 'Upcoming'

            html += f"""
                <tr>
                    <td>{l['name']}</td>
                    <td>{l['loan_type']}</td>
                    <td>{l['bank_name']}</td>
                    <td class="text-center">{l['maturity_date']}</td>
                    <td class="text-center"><strong>{days_left}</strong></td>
                    <td class="text-right">{_fmt(l['outstanding'])}</td>
                    <td class="text-center"><span class="report-badge {urgency_class}">{urgency_label}</span></td>
                    <td class="text-center">{_state_badge(l['state'])}</td>
                </tr>
            """

        html += f"""
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="5"><strong>Total Outstanding (Maturing)</strong></td>
                    <td class="text-right">{_fmt(total_outstanding)}</td>
                    <td colspan="2"></td>
                </tr>
            </tfoot>
        </table>
        """
        return html

    # ═════════════════════════════════════════════════════════════════════════
    # REPORT 5 — Loan Exposure
    # ═════════════════════════════════════════════════════════════════════════
    def _generate_exposure_report(self):
        loans = self._collect_all_loans()
        if not loans:
            return '<p style="padding:20px;color:#888;">No loan records found matching the selected filters.</p>'

        group_key = self.group_by or 'bank'
        group_labels = {
            'bank': 'Bank',
            'business_unit': 'Business Unit',
            'state': 'Status',
        }
        group_label = group_labels.get(group_key, group_key.title())

        # Build grouping
        groups = {}
        for l in loans:
            if group_key == 'bank':
                key = l['bank_name'] or 'Unknown'
            elif group_key == 'state':
                key = (l['state'] or 'draft').replace('_', ' ').title()
            else:
                key = 'N/A'
            groups.setdefault(key, []).append(l)

        total_approved = sum(l['approved'] for l in loans)
        total_outstanding = sum(l['outstanding'] for l in loans)

        # Sort groups by outstanding descending
        sorted_groups = sorted(groups.items(), key=lambda g: sum(l['outstanding'] for l in g[1]), reverse=True)

        html = f"""
        <div class="report-summary-box">
            <strong>Exposure Analysis by {group_label}</strong> &mdash;
            Total Facilities: <strong>{len(loans)}</strong> |
            Total Approved: <strong>{_fmt(total_approved)}</strong> |
            Total Outstanding: <strong>{_fmt(total_outstanding)}</strong>
        </div>
        <table class="loan-report-table">
            <caption>Loan Exposure Report — Grouped by {group_label}</caption>
            <thead>
                <tr>
                    <th>{group_label}</th>
                    <th class="text-center">Number of Loans</th>
                    <th class="text-right">Total Approved</th>
                    <th class="text-right">Total Outstanding</th>
                    <th class="text-right">Exposure %</th>
                </tr>
            </thead>
            <tbody>
        """
        for group_name, group_loans in sorted_groups:
            g_approved = sum(l['approved'] for l in group_loans)
            g_outstanding = sum(l['outstanding'] for l in group_loans)
            exposure_pct = (g_outstanding / total_outstanding * 100) if total_outstanding else 0

            html += f"""
                <tr>
                    <td><strong>{group_name}</strong></td>
                    <td class="text-center">{len(group_loans)}</td>
                    <td class="text-right">{_fmt(g_approved)}</td>
                    <td class="text-right">{_fmt(g_outstanding)}</td>
                    <td class="text-right" style="font-weight:600;">{_fmt(exposure_pct, 1)}%</td>
                </tr>
            """

        html += f"""
            </tbody>
            <tfoot>
                <tr>
                    <td><strong>Grand Total</strong></td>
                    <td class="text-center">{len(loans)}</td>
                    <td class="text-right">{_fmt(total_approved)}</td>
                    <td class="text-right">{_fmt(total_outstanding)}</td>
                    <td class="text-right" style="font-weight:700;">100.0%</td>
                </tr>
            </tfoot>
        </table>
        """

        # ── Detailed breakdown per group ──────────────────────────────────
        html += f'<h3 style="margin-top:32px;color:#714b67;">Detailed Breakdown by {group_label}</h3>'
        for group_name, group_loans in sorted_groups:
            html += f"""
            <table class="loan-report-table">
                <caption>{group_name}</caption>
                <thead>
                    <tr>
                        <th>Loan ID</th>
                        <th>Loan Type</th>
                        <th class="text-right">Approved</th>
                        <th class="text-right">Outstanding</th>
                        <th class="text-right">Interest Rate (%)</th>
                        <th class="text-center">Maturity</th>
                        <th class="text-center">Status</th>
                    </tr>
                </thead>
                <tbody>
            """
            for l in group_loans:
                maturity_str = str(l['maturity_date']) if l['maturity_date'] else '—'
                html += f"""
                    <tr>
                        <td>{l['name']}</td>
                        <td>{l['loan_type']}</td>
                        <td class="text-right">{_fmt(l['approved'])}</td>
                        <td class="text-right">{_fmt(l['outstanding'])}</td>
                        <td class="text-right">{_fmt(l['interest_rate'], 4)}</td>
                        <td class="text-center">{maturity_str}</td>
                        <td class="text-center">{_state_badge(l['state'])}</td>
                    </tr>
                """
            g_approved = sum(l['approved'] for l in group_loans)
            g_outstanding = sum(l['outstanding'] for l in group_loans)
            html += f"""
                </tbody>
                <tfoot>
                    <tr>
                        <td colspan="2"><strong>Subtotal</strong></td>
                        <td class="text-right">{_fmt(g_approved)}</td>
                        <td class="text-right">{_fmt(g_outstanding)}</td>
                        <td colspan="3"></td>
                    </tr>
                </tfoot>
            </table>
            """

        return html

    # ═════════════════════════════════════════════════════════════════════════
    # EXPORT METHODS
    # ═════════════════════════════════════════════════════════════════════════
    def _extract_table_data(self):
        """Parse report_html to extract structured table data for export."""
        if not self.report_html:
            return []
        try:
            import bs4
        except ImportError:
            raise UserError(_(
                'The beautifulsoup4 library is required for export. '
                'Install it with: pip install beautifulsoup4'
            ))
        soup = bs4.BeautifulSoup(self.report_html, 'html.parser')
        data = []
        for table in soup.find_all('table'):
            caption = table.find('caption')
            section = caption.get_text(strip=True) if caption else 'Report'
            headers = [th.get_text(strip=True) for th in table.find_all('th')]
            rows = []
            tbody = table.find('tbody')
            if tbody:
                for tr in tbody.find_all('tr'):
                    tds = [td.get_text(strip=True) for td in tr.find_all('td')]
                    if tds:
                        rows.append(tds)
            # Footer
            tfoot = table.find('tfoot')
            footer = []
            if tfoot:
                for tr in tfoot.find_all('tr'):
                    tds = [td.get_text(strip=True) for td in tr.find_all('td')]
                    if tds:
                        footer.append(tds)
            data.append({
                'section': section,
                'headers': headers,
                'rows': rows,
                'footer': footer,
            })
        return data

    def action_export_xlsx(self):
        self.ensure_one()
        if not self.report_html:
            raise UserError(_('Please generate the report first.'))
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter library is required. Install with: pip install xlsxwriter'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Report')

        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'color': '#714b67',
        })
        section_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'bg_color': '#f3edf1',
            'border': 1, 'color': '#714b67',
        })
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#714b67', 'font_color': '#ffffff',
            'border': 1,
        })
        cell_fmt = workbook.add_format({'border': 1})
        footer_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#f3edf1', 'border': 1,
        })

        report_names = dict(self._fields['report_type'].selection)
        report_name = report_names.get(self.report_type, 'Report')

        row_idx = 0
        worksheet.write(row_idx, 0, report_name, title_fmt)
        worksheet.write(row_idx, 1, f'Generated: {fields.Date.context_today(self)}', cell_fmt)
        row_idx += 2

        tables = self._extract_table_data()
        for t in tables:
            worksheet.write(row_idx, 0, t['section'], section_fmt)
            row_idx += 1
            for col_idx, h in enumerate(t['headers']):
                worksheet.write(row_idx, col_idx, h, header_fmt)
            row_idx += 1
            for r in t['rows']:
                for col_idx, val in enumerate(r):
                    worksheet.write(row_idx, col_idx, val, cell_fmt)
                row_idx += 1
            for r in t.get('footer', []):
                for col_idx, val in enumerate(r):
                    worksheet.write(row_idx, col_idx, val, footer_fmt)
                row_idx += 1
            row_idx += 1

        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': f'{report_name}_{fields.Date.context_today(self)}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_export_csv(self):
        self.ensure_one()
        if not self.report_html:
            raise UserError(_('Please generate the report first.'))
        import csv as csv_mod

        output = io.StringIO()
        writer = csv_mod.writer(output)

        report_names = dict(self._fields['report_type'].selection)
        report_name = report_names.get(self.report_type, 'Report')

        writer.writerow([report_name, f'Generated: {fields.Date.context_today(self)}'])
        writer.writerow([])

        tables = self._extract_table_data()
        for t in tables:
            writer.writerow([t['section']])
            if t['headers']:
                writer.writerow(t['headers'])
            for r in t['rows']:
                writer.writerow(r)
            for r in t.get('footer', []):
                writer.writerow(r)
            writer.writerow([])

        attachment = self.env['ir.attachment'].create({
            'name': f'{report_name}_{fields.Date.context_today(self)}.csv',
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue().encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/csv',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_export_pdf(self):
        """Generate a PDF from the report HTML using QWeb report action."""
        self.ensure_one()
        if not self.report_html:
            raise UserError(_('Please generate the report first.'))
        return self.env.ref(
            'overdraft_interest_calculator.action_report_loan_report_wizard_pdf'
        ).report_action(self)
