from odoo import models, fields, api


class PreShipmentLoanLine(models.Model):
    _name = 'preshipment.loan.line'
    _description = 'Pre-Shipment Loan Entry'
    _order = 'date asc, id asc'

    loan_id = fields.Many2one(
        'preshipment.loan',
        string='Loan',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        related='loan_id.currency_id',
        store=True,
        readonly=True,
    )
    foreign_currency_id = fields.Many2one(
        related='loan_id.foreign_currency_id',
        store=True,
        readonly=True,
    )
    entry_type = fields.Selection([
        ('utilization', 'Utilization Entry'),
        ('currency', 'Foreign Currency Entry'),
    ], string='Entry Type', required=True, default='utilization')

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )
    # ----- Loan Utilisation -----
    amount_used = fields.Monetary(
        string='Loan Amount Used',
        currency_field='currency_id',
        help='Amount drawn from the loan facility on this date.',
    )
    # ----- Foreign Currency Deposit -----
    currency_deposited = fields.Float(
        string='Foreign Currency Deposited',
        digits=(16, 4),
        help='Amount of foreign currency delivered to the bank on this date.',
    )
    conversion_rate = fields.Float(
        string='Conversion Rate',
        digits=(16, 6),
        default=1.0,
        help='Rate to convert foreign currency to local currency.',
    )
    amount_deposited_local = fields.Monetary(
        string='Amount Deposited (Local)',
        currency_field='currency_id',
        compute='_compute_amount_deposited_local',
        store=True,
        help='Amount deposited in local currency equivalent.',
    )
    # ----- Interest -----
    interest = fields.Monetary(
        string='Interest Charged',
        currency_field='currency_id',
        compute='_compute_interest',
        store=True,
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_total_amount',
        store=True,
        help='Loan Amount Used + Interest Charged.',
    )
    # ----- Penalty -----
    penalty = fields.Monetary(
        string='Penalty',
        currency_field='currency_id',
        help='Penalty charged for late/insufficient currency delivery (computed at loan level).',
    )
    notes = fields.Text(string='Notes')

    @api.depends('currency_deposited', 'conversion_rate', 'entry_type')
    def _compute_amount_deposited_local(self):
        for line in self:
            if line.entry_type == 'currency':
                line.amount_deposited_local = (line.currency_deposited or 0.0) * (line.conversion_rate or 0.0)
            else:
                line.amount_deposited_local = 0.0

    @api.depends('amount_used', 'interest', 'entry_type')
    def _compute_total_amount(self):
        for line in self:
            if line.entry_type == 'utilization':
                line.total_amount = (line.amount_used or 0.0) + (line.interest or 0.0)
            else:
                line.total_amount = 0.0

    @api.depends('amount_used', 'date', 'entry_type', 'loan_id.start_date', 'loan_id.annual_interest_rate')
    def _compute_interest(self):
        for line in self:
            if line.entry_type == 'utilization' and line.loan_id and line.loan_id.start_date and line.date:
                days = (line.date - line.loan_id.start_date).days
                if days > 0:
                    daily_rate = (line.loan_id.annual_interest_rate / 100.0) / 365.0
                    line.interest = round(line.amount_used * daily_rate * days, 2)
                else:
                    line.interest = 0.0
            else:
                line.interest = 0.0

    @api.onchange('entry_type')
    def _onchange_entry_type(self):
        if self.entry_type == 'utilization':
            self.currency_deposited = 0.0
            self.conversion_rate = 1.0
        elif self.entry_type == 'currency':
            self.amount_used = 0.0
