import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OverdraftLine(models.Model):
    _name = 'overdraft.line'
    _description = 'Overdraft Daily Line'
    _order = 'date asc, id asc'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    overdraft_id = fields.Many2one(
        'overdraft.interest',
        string='Overdraft',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='overdraft_id.currency_id',
        store=True,
        readonly=True,
    )

    date = fields.Date(
        string='Date',
        required=True,
    )
    debit = fields.Monetary(
        string='Debit',
        default=0.0,
        currency_field='currency_id',
        help='Money withdrawn / used from overdraft (increases negative balance)',
    )
    payment = fields.Monetary(
        string='Payment',
        default=0.0,
        currency_field='currency_id',
        help='Money paid back to reduce the overdraft',
    )
    interest_payment = fields.Monetary(
        string='Interest Payment',
        default=0.0,
        currency_field='currency_id',
        help='Portion of the payment allocated to cumulative interest',
    )
    principal_payment = fields.Monetary(
        string='Principal Payment',
        default=0.0,
        currency_field='currency_id',
        help='Portion of the payment allocated to reducing the balance',
    )
    penalty_payment = fields.Monetary(
        string='Penalty Payment',
        default=0.0,
        currency_field='currency_id',
        help='Money paid specifically for the penalty',
    )
    balance = fields.Monetary(
        string='Balance',
        currency_field='currency_id',
        readonly=True,
        help='Account balance at end of day. Negative means overdrawn.',
    )

    daily_interest = fields.Monetary(
        string='Daily Interest',
        currency_field='currency_id',
        readonly=True,
        help='Interest charged for this day: |Balance| × Daily Rate',
    )
    penalty_accrued = fields.Monetary(
        string='Penalty Accrued',
        default=0.0,
        currency_field='currency_id',
        readonly=True,
        help='Penalty accrued at the 90-day mark',
    )
    cumulative_interest = fields.Monetary(
        string='Cumulative Interest',
        currency_field='currency_id',
        readonly=True,
        help='Running total of all interest + penalties up to this day',
    )
    notes = fields.Text(string='Notes')

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        is_user_action = not self.env.su and not self.env.context.get('skip_access_check')
        if is_user_action:
            from markupsafe import Markup
            for line in lines:
                if line.debit > 0 or line.payment > 0 or line.penalty_payment > 0:
                    user_name = self.env.user.name
                    date_str = line.date.strftime('%Y-%m-%d') if line.date else ''
                    symbol = line.currency_id.symbol or ''

                    details = []
                    if line.debit > 0:
                        details.append(f"Debit: {line.debit:,.2f} {symbol}")
                    if line.payment > 0:
                        details.append(f"Payment: {line.payment:,.2f} {symbol}")
                    if line.penalty_payment > 0:
                        details.append(f"Penalty Payment: {line.penalty_payment:,.2f} {symbol}")

                    details_str = " | ".join(details)
                    message_body = Markup(
                        f"<b>Overdraft Entry Recorded ({date_str}):</b> {details_str} by {user_name}"
                    )
                    line.overdraft_id.message_post(body=message_body, message_type='comment', subtype_xmlid='mail.mt_note')
        return lines

    def write(self, vals):
        """Prevent non-managers from editing restricted fields and log user edits."""
        is_user_action = not self.env.su and not self.env.context.get('skip_access_check')
        if is_user_action:
            if not self.env.user.has_group(
                'overdraft_interest_calculator.group_overdraft_editor'
            ):
                allowed_fields = {'debit', 'payment', 'penalty_payment', 'notes'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError(_(
                        'Only editors can edit computed fields. '
                        'You can modify Debit, Payment, Penalty Payment, and Notes.'
                    ))

        res = super().write(vals)

        if is_user_action:
            from markupsafe import Markup
            for line in self:
                if 'debit' in vals or 'payment' in vals or 'penalty_payment' in vals:
                    user_name = self.env.user.name
                    date_str = line.date.strftime('%Y-%m-%d') if line.date else ''
                    symbol = line.currency_id.symbol or ''

                    details = []
                    if 'debit' in vals:
                        details.append(f"Debit: {vals['debit']:,.2f} {symbol}")
                    if 'payment' in vals:
                        details.append(f"Payment: {vals['payment']:,.2f} {symbol}")
                    if 'penalty_payment' in vals:
                        details.append(f"Penalty Payment: {vals['penalty_payment']:,.2f} {symbol}")

                    details_str = " | ".join(details)
                    message_body = Markup(
                        f"<b>Overdraft Entry Updated ({date_str}):</b> {details_str} by {user_name}"
                    )
                    line.overdraft_id.message_post(body=message_body, message_type='comment', subtype_xmlid='mail.mt_note')

        return res
