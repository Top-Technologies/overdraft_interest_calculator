from odoo import models, fields, api


class MerchandiseLoanLine(models.Model):
    _name = 'merchandise.loan.line'
    _description = 'Merchandise Loan — Goods Release Entry'
    _order = 'date asc, id asc'

    loan_id = fields.Many2one(
        'merchandise.loan',
        string='Loan',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        related='loan_id.currency_id',
        store=True,
        readonly=True,
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )

    # ── The user enters the quantity of goods to release ──
    goods_released_quantity = fields.Float(
        string='Goods to Release (Qty)',
        digits=(16, 3),
        help='Number of goods you want to take from the warehouse.',
    )

    # ── Auto-calculated fields ──
    interest = fields.Monetary(
        string='Interest',
        currency_field='currency_id',
        help='Daily interest accrued from last payment/activation until this date.',
    )
    payment_amount = fields.Monetary(
        string='Total Payment',
        currency_field='currency_id',
        help='Principal (qty × unit price) + Interest',
    )
    outstanding_after = fields.Monetary(
        string='Outstanding After',
        currency_field='currency_id',
        compute='_compute_outstanding_after',
        store=True,
        readonly=True,
    )
    notes = fields.Text(string='Notes')

    # -------------------------------------------------------------------------
    # COMPUTE — outstanding after this line
    # -------------------------------------------------------------------------
    @api.depends('payment_amount', 'interest',
                 'loan_id.bank_amount', 'loan_id.loan_line_ids.payment_amount',
                 'loan_id.loan_line_ids.interest')
    def _compute_outstanding_after(self):
        for line in self:
            loan = line.loan_id
            if not loan:
                line.outstanding_after = 0.0
                continue
            # Sum only principal portions (payment - interest) for all lines up to this one
            principal_paid = 0.0
            for l in loan.loan_line_ids.sorted('date'):
                principal_paid += (l.payment_amount or 0.0) - (l.interest or 0.0)
                if l.id == line.id:
                    break
            line.outstanding_after = max(loan.bank_amount - principal_paid, 0.0)

    # -------------------------------------------------------------------------
    # HOOKS — trigger recalculation when lines change
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Recalculate interest for all affected loans
        loans = lines.mapped('loan_id')
        loans._recalculate_line_interest()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'goods_released_quantity' in vals or 'date' in vals:
            loans = self.mapped('loan_id')
            loans._recalculate_line_interest()
        return res
