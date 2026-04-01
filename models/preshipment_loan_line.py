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
    # ----- Interest -----
    interest = fields.Monetary(
        string='Interest Charged',
        currency_field='currency_id',
    )
    # ----- Penalty -----
    penalty = fields.Monetary(
        string='Penalty',
        currency_field='currency_id',
        help='Penalty charged for late/insufficient currency delivery.',
    )
    notes = fields.Text(string='Notes')
