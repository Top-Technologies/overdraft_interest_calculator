from odoo import models, fields, api, _
from odoo.exceptions import UserError


class TermLoanPaymentWizard(models.TransientModel):
    _name = 'term.loan.payment.wizard'
    _description = 'Record Term Loan Extra Payment'

    loan_id = fields.Many2one(
        'term.loan',
        string='Term Loan',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='loan_id.currency_id',
        readonly=True,
    )
    line_id = fields.Many2one(
        'term.loan.line',
        string='Payment Line',
        required=True,
        domain="[('loan_id', '=', loan_id), ('ending_balance', '>', 0)]",
        help='Select the schedule line to apply the extra payment to.',
    )
    amount = fields.Monetary(
        string='Extra Payment Amount',
        required=True,
        currency_field='currency_id',
    )
    memo = fields.Char(string='Memo')

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        """Auto-select the first unpaid line."""
        if self.loan_id:
            lines = self.loan_id.loan_line_ids.sorted('payment_number')
            unpaid = lines.filtered(lambda l: l.ending_balance > 0)
            if unpaid:
                self.line_id = unpaid[0].id

    def action_confirm(self):
        """Record the extra payment on the selected schedule line
        and trigger recalculation."""
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))

        line = self.line_id
        if not line:
            raise UserError(_('Please select a payment line.'))

        # Update the extra_payment on the line
        line.write({
            'extra_payment': line.extra_payment + self.amount,
        })

        # Trigger recalculation of the schedule
        self.loan_id.action_recalculate_schedule()

        return {'type': 'ir.actions.act_window_close'}
