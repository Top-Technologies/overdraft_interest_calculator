from odoo import models, fields, api, _
from odoo.exceptions import UserError


class OverdraftPaymentWizard(models.TransientModel):
    _name = 'overdraft.payment.wizard'
    _description = 'Record Overdraft Payment'

    overdraft_id = fields.Many2one(
        'overdraft.interest',
        string='Overdraft',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='overdraft_id.currency_id',
        readonly=True,
    )
    date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(
        string='Payment Amount',
        required=True,
        currency_field='currency_id',
    )
    memo = fields.Char(string='Memo')

    def action_confirm(self):
        """Record the payment on the overdraft daily line."""
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))

        overdraft = self.overdraft_id
        # Find or create the daily line for this date
        line = self.env['overdraft.line'].search([
            ('overdraft_id', '=', overdraft.id),
            ('date', '=', self.date),
        ], limit=1)

        if line:
            # Add to existing payment
            line.with_context(skip_access_check=True).write({
                'payment': line.payment + self.amount,
                'notes': self.memo or line.notes,
            })
        else:
            self.env['overdraft.line'].with_context(skip_access_check=True).create({
                'overdraft_id': overdraft.id,
                'date': self.date,
                'payment': self.amount,
                'notes': self.memo,
            })

        return {'type': 'ir.actions.act_window_close'}
