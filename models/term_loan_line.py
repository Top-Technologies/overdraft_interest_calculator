from odoo import models, fields


class TermLoanLine(models.Model):
    _name = 'term.loan.line'
    _description = 'Term Loan Amortization Line'
    _order = 'payment_number asc'

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
        string='Total Payment',
        readonly=True,
        currency_field='currency_id',
        help='Scheduled payment + Extra payment',
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
