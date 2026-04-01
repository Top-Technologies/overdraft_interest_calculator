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
    penalty = fields.Monetary(
        string='Extra Interest (Penalty)',
        default=0.0,
        currency_field='currency_id',
        help='Additional penalty interest (editable — enter only when applicable)',
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
    def write(self, vals):
        """Prevent non-managers from editing restricted fields."""
        # Allow system/sudo writes (e.g. from action_calculate_amortization)
        if self.env.su or self.env.context.get('skip_access_check'):
            return super().write(vals)
        if not self.env.user.has_group(
            'overdraft_interest_calculator.group_overdraft_manager'
        ):
            # Allow users to edit only these fields
            allowed_fields = {'debit', 'payment', 'penalty', 'notes'}
            if not set(vals.keys()).issubset(allowed_fields):
                raise UserError(_(
                    'Only managers can edit computed fields. '
                    'You can modify Debit, Payment, Penalty, and Notes.'
                ))
        return super().write(vals)
