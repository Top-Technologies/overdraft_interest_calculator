from odoo import models, fields, api


class TermLoanLine(models.Model):
    _name = 'term.loan.line'
    _description = 'Term Loan Amortization Line'
    _order = 'payment_number asc'

    @api.depends('payment_number')
    def _compute_display_name(self):
        for line in self:
            line.display_name = f"Pmt No. {line.payment_number}"

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    loan_id = fields.Many2one(
        'term.loan',
        string='Term Loan',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='loan_id.currency_id',
        store=True,
        readonly=True,
    )

    payment_number = fields.Integer(
        string='Pmt. No.',
        readonly=True,
        help='Payment sequence number',
    )
    payment_date = fields.Date(
        string='Payment Date',
        readonly=True,
        help='The date the payment is due',
    )
    beginning_balance = fields.Monetary(
        string='Beginning Balance',
        readonly=True,
        currency_field='currency_id',
        help='Loan balance before the payment',
    )
    scheduled_payment = fields.Monetary(
        string='Scheduled Payment',
        readonly=True,
        currency_field='currency_id',
        help='The fixed required payment amount',
    )
    extra_payment = fields.Monetary(
        string='Extra Payment',
        currency_field='currency_id',
        help='Additional amount paid on top of scheduled payment',
    )
    total_payment = fields.Monetary(
        string='Base Payment',
        readonly=True,
        currency_field='currency_id',
        help='Scheduled payment + Extra payment',
    )
    penalty_amount = fields.Monetary(
        string='Penalty Accrued',
        compute='_compute_penalty_amount',
        currency_field='currency_id',
        help='Penalty accrued for this specific payment if delayed.',
    )
    total_due = fields.Monetary(
        string='Total Due',
        compute='_compute_total_due',
        currency_field='currency_id',
        help='Base Payment + Penalty Accrued',
    )
    interest = fields.Monetary(
        string='Interest',
        readonly=True,
        currency_field='currency_id',
        help='Cost of borrowing for this period',
    )
    principal = fields.Monetary(
        string='Principal',
        readonly=True,
        currency_field='currency_id',
        help='Portion of payment that reduces the loan balance',
    )
    ending_balance = fields.Monetary(
        string='Ending Balance',
        readonly=True,
        currency_field='currency_id',
        help='Remaining loan balance after the payment',
    )
    cumulative_interest = fields.Monetary(
        string='Cumulative Interest',
        readonly=True,
        currency_field='currency_id',
        help='Total interest paid from start up to this payment',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Payment Status / Delinquency Tracking
    # -------------------------------------------------------------------------
    is_paid = fields.Boolean(
        string='Paid',
        default=False,
        help='Check once this scheduled payment has actually been settled.',
    )
    paid_date = fields.Date(
        string='Paid Date',
        help='The date this scheduled payment was actually settled.',
    )
    is_overdue = fields.Boolean(
        string='Overdue',
        compute='_compute_overdue',
        help='True when this payment is unpaid and past its due date.',
    )
    days_overdue = fields.Integer(
        string='Days Past Due',
        compute='_compute_overdue',
        help='Number of calendar days this payment is past its due date.',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('is_paid', 'payment_date')
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for line in self:
            if not line.is_paid and line.payment_date and line.payment_date < today:
                line.is_overdue = True
                line.days_overdue = (today - line.payment_date).days
            else:
                line.is_overdue = False
                line.days_overdue = 0

    @api.depends('is_paid', 'payment_date', 'total_payment', 'loan_id.penalty_rate_tier1', 'loan_id.penalty_rate_tier2', 'loan_id.penalty_rate_tier3')
    def _compute_penalty_amount(self):
        today = fields.Date.context_today(self)
        for line in self:
            penalty = 0.0
            if line.is_overdue and line.loan_id:
                days_overdue = line.days_overdue
                base = line.total_payment
                tier1_days = min(days_overdue, 30)
                tier2_days = min(max(days_overdue - 30, 0), 30)
                tier3_days = max(days_overdue - 60, 0)
                
                if tier1_days > 0 and line.loan_id.penalty_rate_tier1:
                    penalty += base * (line.loan_id.penalty_rate_tier1 / 100.0 / 365.0) * tier1_days
                if tier2_days > 0 and line.loan_id.penalty_rate_tier2:
                    penalty += base * (line.loan_id.penalty_rate_tier2 / 100.0 / 365.0) * tier2_days
                if tier3_days > 0 and line.loan_id.penalty_rate_tier3:
                    penalty += base * (line.loan_id.penalty_rate_tier3 / 100.0 / 365.0) * tier3_days
            
            line.penalty_amount = round(penalty, 2)

    @api.depends('total_payment', 'penalty_amount')
    def _compute_total_due(self):
        for line in self:
            line.total_due = line.total_payment + line.penalty_amount

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        is_user_action = not self.env.su and not self.env.context.get('skip_access_check')
        if is_user_action:
            from markupsafe import Markup
            for line in self:
                if 'extra_payment' in vals or 'is_paid' in vals:
                    user_name = self.env.user.name
                    symbol = line.currency_id.symbol or ''
                    pmt_no = line.payment_number

                    details = []
                    if 'extra_payment' in vals:
                        details.append(f"Extra Payment: {vals['extra_payment']:,.2f} {symbol}")
                    if 'is_paid' in vals and vals['is_paid']:
                        details.append(f"Status: Marked Paid")

                    if details:
                        details_str = " | ".join(details)
                        message_body = Markup(
                            f"<b>Term Loan Entry Updated (Pmt #{pmt_no}):</b> {details_str} by {user_name}"
                        )
                        line.loan_id.message_post(body=message_body, message_type='comment', subtype_xmlid='mail.mt_note')
        return res