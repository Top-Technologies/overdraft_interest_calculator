import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OverdraftInterest(models.Model):
    _name = 'overdraft.interest'
    _description = 'Overdraft Interest'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    # -------------------------------------------------------------------------
    # DEFAULT HELPERS
    # -------------------------------------------------------------------------
    @api.model
    def _default_currency(self):
        return self.env.company.currency_id

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, copy=False)

    # Bank fields
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        domain="[('type', '=', 'bank')]",
        tracking=True,
    )
    bank_id = fields.Many2one(
        'res.bank',
        string='Bank',
        related='bank_journal_id.bank_id',
        store=True,
        readonly=True,
    )

    # Date fields
    date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    due_date = fields.Date(
        string='End Date',
        tracking=True,
    )

    # Currency
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=_default_currency,
        required=True,
    )

    # Rates
    daily_interest_rate = fields.Float(
        string='Daily Interest Rate (%)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
    )
    daily_penalty_rate = fields.Float(
        string='Daily Penalty Rate (%)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
    )

    # Overdraft limit
    overdraft_limit = fields.Monetary(
        string='Overdraft Limit',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )

    # Lines
    overdraft_line_ids = fields.One2many(
        'overdraft.line',
        'overdraft_id',
        string='Overdraft Entries',
        copy=True,
    )

    # -------------------------------------------------------------------------
    # COMPUTED SUMMARY FIELDS
    # -------------------------------------------------------------------------
    total_interest = fields.Monetary(
        string='Total Interest',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_penalty = fields.Monetary(
        string='Total Penalty',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    remaining_overdraft = fields.Monetary(
        string='Remaining Overdraft',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_outstanding = fields.Monetary(
        string='Total Outstanding',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    projected_daily_interest = fields.Monetary(
        string='Projected Daily Interest',
        compute='_compute_projected_interest',
        store=True,
        currency_field='currency_id',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends(
        'overdraft_line_ids.amount',
        'overdraft_line_ids.interest',
        'overdraft_line_ids.penalty',
        'overdraft_line_ids.payment',
        'overdraft_limit',
    )
    def _compute_totals(self):
        for record in self:
            lines = record.overdraft_line_ids
            total_amount = sum(abs(l.amount) for l in lines)
            record.total_interest = sum(l.interest for l in lines)
            record.total_penalty = sum(l.penalty for l in lines)
            record.total_paid = sum(l.payment for l in lines)

            outstanding_principal = max(total_amount - record.total_paid, 0)
            record.remaining_overdraft = record.overdraft_limit - outstanding_principal
            record.total_outstanding = (
                total_amount
                + record.total_interest
                + record.total_penalty
                - record.total_paid
            )

    @api.depends('remaining_overdraft', 'daily_interest_rate')
    def _compute_projected_interest(self):
        for record in self:
            if record.remaining_overdraft > 0 and record.daily_interest_rate:
                record.projected_daily_interest = (
                    record.remaining_overdraft
                    * (record.daily_interest_rate / 100.0)
                    / 365.0
                )
            else:
                record.projected_daily_interest = 0.0

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('overdraft.interest')
                    or 'New'
                )
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------------------------
    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft records can be submitted.'))
            record.state = 'submitted'

    def action_approve(self):
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('Only submitted records can be approved.'))
            record.state = 'approved'

    def action_reject(self):
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('Only submitted records can be rejected.'))
            record.state = 'rejected'

    def action_reset_to_draft(self):
        for record in self:
            if record.state not in ('rejected', 'submitted'):
                raise UserError(_(
                    'Only rejected or submitted records can be reset to draft.'
                ))
            record.state = 'draft'

    def action_close(self):
        for record in self:
            if record.state != 'approved':
                raise UserError(_('Only approved records can be closed.'))
            record.state = 'closed'
