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
    payment_type = fields.Selection([
        ('normal', 'Normal Payment'),
        ('penalty', 'Penalty Payment')
    ], string='Payment Type', default='normal', required=True)
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
            vals = {}
            if self.memo:
                existing_notes = line.notes or ''
                vals['notes'] = (existing_notes + '\n' + self.memo).strip()
            if self.payment_type == 'normal':
                vals['payment'] = line.payment + self.amount
            else:
                vals['penalty_payment'] = line.penalty_payment + self.amount
                
            line.sudo().write(vals)
        else:
            vals = {
                'overdraft_id': overdraft.id,
                'date': self.date,
                'notes': self.memo,
            }
            if self.payment_type == 'normal':
                vals['payment'] = self.amount
            else:
                vals['penalty_payment'] = self.amount
            self.env['overdraft.line'].sudo().create(vals)

        # Recalculate amortization to reflect new payments
        overdraft.action_calculate_amortization()

        # Post clean log note in chatter using Markup
        from markupsafe import Markup
        user_name = self.env.user.name
        formatted_amount = f"{self.amount:,.2f} {self.currency_id.symbol or ''}"
        pay_type_label = "Penalty Payment" if self.payment_type == 'penalty' else "Payment"

        message_body = Markup("<b>%s Recorded:</b> %s on %s by %s") % (pay_type_label, formatted_amount, self.date, user_name)
        if self.memo:
            message_body += Markup(" (Memo: %s)") % self.memo
        overdraft.message_post(body=message_body, message_type='comment', subtype_xmlid='mail.mt_note')

        return {'type': 'ir.actions.act_window_close'}
