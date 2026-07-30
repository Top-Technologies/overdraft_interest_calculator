import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class OverdraftInterest(models.Model):
    _name = 'overdraft.interest'
    _description = 'Overdraft Interest'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

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
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )

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

    # Period
    date_from = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )

    # Currency
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=_default_currency,
        required=True,
    )

    # Interest rates
    annual_interest_rate = fields.Float(
        string='Annual Interest Rate (%)',
        digits=(16, 6),
        required=True,
        tracking=True,
        help='Annual overdraft interest rate as a percentage (e.g. 21.35)',
    )
    three_month_penalty_rate = fields.Float(
        string='3-Month Penalty Rate (%)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Flat penalty rate applied to accrued interest every 90 days (e.g. 5.0)',
    )

    # Overdraft limit
    overdraft_limit = fields.Monetary(
        string='Overdraft Limit',
        required=True,
        currency_field='currency_id',
        tracking=True,
        help='Maximum allowed negative balance (enter as positive value)',
    )

    # OD Account Number
    od_account_number = fields.Char(
        string='OD Account Number',
        tracking=True,
        help='Bank account number linked to the overdraft facility.',
    )

    # Purpose
    purpose = fields.Text(
        string='Purpose',
        tracking=True,
        help='Intended business use of the overdraft facility (e.g. working capital, procurement bridging).',
    )

    # Collateral Documents
    collateral_document_ids = fields.Many2many(
        'ir.attachment',
        'overdraft_collateral_attachment_rel',
        'overdraft_id',
        'attachment_id',
        string='Collateral Documents',
        help='Attach security/collateral documents for this overdraft facility.',
    )

    # Calculation state
    is_calculated = fields.Boolean(
        string='Is Calculated',
        default=False,
        copy=False,
        help='Whether the amortization has been calculated at least once',
    )

    # Lines
    overdraft_line_ids = fields.One2many(
        'overdraft.line',
        'overdraft_id',
        string='Daily Entries',
        copy=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Account Links
    # -------------------------------------------------------------------------
    account_receivable_id = fields.Many2one(
        'account.account',
        string='Account Receivable',
        tracking=True,
        domain="[('account_type', '=', 'asset_receivable')]",
    )
    account_payable_id = fields.Many2one(
        'account.account',
        string='Account Payable',
        tracking=True,
        domain="[('account_type', '=', 'liability_payable')]",
    )
    income_account_id = fields.Many2one(
        'account.account',
        string='Income Account',
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
    )

    # -------------------------------------------------------------------------
    # FIELDS — Accounting Links
    # -------------------------------------------------------------------------
    move_ids = fields.One2many(
        'account.move', 'overdraft_id',
        string='Journal Entries',
    )
    bill_ids = fields.One2many(
        'account.move', 'overdraft_id',
        string='Bills',
        domain=[('move_type', '=', 'in_invoice')],
    )
    move_count = fields.Integer(
        compute='_compute_move_count',
        string='Journal Entry Count',
    )
    bill_count = fields.Integer(
        compute='_compute_move_count',
        string='Bill Count',
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
    total_debit = fields.Monetary(
        string='Total Debit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_payment = fields.Monetary(
        string='Total Payment',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    current_balance = fields.Monetary(
        string='Current Balance',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    current_utilization = fields.Monetary(
        string='Current Utilization',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Amount currently drawn from the overdraft facility (absolute value of overdrawn balance).',
    )
    available_balance = fields.Monetary(
        string='Available Balance',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Remaining unused overdraft capacity: Approved Limit − Current Utilization.',
    )
    interest_charged = fields.Monetary(
        string='Interest Charged (Period)',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total interest + penalty charged on the utilized overdraft balance for this period.',
    )
    outstanding_interest = fields.Monetary(
        string='Outstanding Interest',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Current unpaid cumulative interest.',
    )
    outstanding_penalty = fields.Monetary(
        string='Outstanding Penalty',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Current unpaid penalty.',
    )
    total_penalty_payment = fields.Monetary(
        string='Total Penalty Payment',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('move_ids', 'bill_ids')
    def _compute_move_count(self):
        for record in self:
            moves = self.env['account.move'].search([
                ('overdraft_id', '=', record.id),
            ])
            record.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            record.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

    @api.depends(
        'overdraft_line_ids.debit',
        'overdraft_line_ids.payment',
        'overdraft_line_ids.daily_interest',
        'overdraft_line_ids.penalty_accrued',
        'overdraft_line_ids.penalty_payment',
        'overdraft_line_ids.cumulative_interest',
        'overdraft_line_ids.balance',
    )
    def _compute_totals(self):
        for record in self:
            lines = record.overdraft_line_ids
            record.total_debit = sum(l.debit for l in lines)
            record.total_payment = sum(l.payment for l in lines)
            record.total_interest = sum(l.daily_interest for l in lines)
            record.total_penalty = sum(l.penalty_accrued for l in lines)
            record.total_penalty_payment = sum(l.penalty_payment for l in lines)
            
            # Outstanding penalty
            record.outstanding_penalty = max(0.0, record.total_penalty - record.total_penalty_payment)

            # Current balance and outstanding interest are from the last line
            if lines:
                sorted_lines = lines.sorted('date')
                last_line = sorted_lines[-1]
                record.current_balance = last_line.balance
                # outstanding_interest is the cumulative before today + today's interest
                record.outstanding_interest = last_line.cumulative_interest + last_line.daily_interest
            else:
                record.current_balance = 0.0
                record.outstanding_interest = 0.0
                
            # Derived fields
            record.current_utilization = abs(min(record.current_balance, 0.0))
            record.available_balance = max(record.overdraft_limit - record.current_utilization, 0.0)
            record.interest_charged = record.total_interest + record.total_penalty

    @api.constrains('annual_interest_rate')
    def _check_interest_rate(self):
        for record in self:
            if record.annual_interest_rate < 0:
                raise ValidationError(_('Interest rate cannot be negative.'))

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('purpose'):
                raise UserError(_("Facility Purpose is compulsory when creating a new loan."))
            col = vals.get('collateral_document_ids')
            has_doc = False
            if col and isinstance(col, (list, tuple)):
                for cmd in col:
                    if isinstance(cmd, (list, tuple)):
                        if cmd[0] == 6 and cmd[2]:
                            has_doc = True
                        elif cmd[0] in (4, 0, 1, 2):
                            has_doc = True
            if not has_doc:
                raise UserError(_("At least one Collateral Document must be attached when creating a new loan."))

            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('overdraft.interest')
                    or 'New'
                )
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # AMORTIZATION CALCULATION
    # -------------------------------------------------------------------------
    def action_calculate_amortization(self):
        """Generate or recalculate daily overdraft amortization lines."""
        for record in self:
            if not record.date_from or not record.date_to:
                raise UserError(_('Please set both Start Date and End Date.'))
            if record.date_to < record.date_from:
                raise UserError(_('End Date must be after Start Date.'))
            if record.annual_interest_rate <= 0:
                raise UserError(_('Annual Interest Rate must be greater than zero.'))
            if record.overdraft_limit <= 0:
                raise UserError(_('Overdraft Limit must be greater than zero.'))

            daily_rate = record.annual_interest_rate / 365.0 / 100.0

            # Collect existing user-entered data (payments & penalties) from ALL lines,
            # including those outside the new date range, so nothing is lost.
            existing_data = {}
            for line in record.overdraft_line_ids:
                existing_data[line.date] = {
                    'debit': line.debit,
                    'payment': line.payment,
                    'penalty_payment': line.penalty_payment,
                    'notes': line.notes,
                }

            # Remove only lines that fall within the new date range — they will be
            # recreated with freshly recalculated values below. Lines that fall
            # OUTSIDE the new range (historical data) are preserved untouched.
            lines_in_range = record.overdraft_line_ids.filtered(
                lambda l: record.date_from <= l.date <= record.date_to
            )
            lines_in_range.unlink()

            # Generate daily lines
            current_date = record.date_from
            end_date = record.date_to
            balance = 0.0
            cumulative_interest = 0.0
            days_since_interest_payment = 0
            lines_to_create = []

            while current_date <= end_date:
                data = existing_data.get(current_date, {})
                debit = data.get('debit', 0.0)
                payment = data.get('payment', 0.0)
                penalty_payment = data.get('penalty_payment', 0.0)
                notes = data.get('notes', '')

                # 1. Payment allocation
                interest_payment = min(payment, cumulative_interest)
                principal_payment = payment - interest_payment

                # 2. Update balance: subtract debit (money taken out), add principal_payment
                balance = balance - debit + principal_payment

                if balance < -record.overdraft_limit:
                    raise UserError(_(
                        'On %(date)s, the withdrawn amount causes the balance (%(balance)s) to exceed the approved overdraft limit of %(limit)s.',
                        date=current_date,
                        balance=abs(balance),
                        limit=record.overdraft_limit
                    ))

                # Deduct interest payment from cumulative
                cumulative_interest -= interest_payment

                # 3. Penalty Check
                penalty_accrued = 0.0
                if interest_payment > 0:
                    days_since_interest_payment = 0
                else:
                    days_since_interest_payment += 1
                
                if days_since_interest_payment == 90:
                    # Trigger penalty
                    penalty_accrued = round(cumulative_interest * (record.three_month_penalty_rate / 100.0), 2)
                    days_since_interest_payment = 0 # reset counter

                # 4. Calculate daily interest on the negative balance
                if balance < 0:
                    daily_interest = round(abs(balance) * daily_rate, 2)
                else:
                    daily_interest = 0.0

                # Record cumulative_interest before adding today's interest for the daily line
                line_cumulative_interest = cumulative_interest

                # 5. Add today's interest to cumulative for tomorrow
                cumulative_interest += daily_interest

                lines_to_create.append({
                    'overdraft_id': record.id,
                    'date': current_date,
                    'debit': debit,
                    'payment': payment,
                    'interest_payment': interest_payment,
                    'principal_payment': principal_payment,
                    'penalty_payment': penalty_payment,
                    'balance': round(balance, 2),
                    'daily_interest': daily_interest,
                    'penalty_accrued': penalty_accrued,
                    'cumulative_interest': round(line_cumulative_interest, 2),
                    'notes': notes,
                })

                current_date += timedelta(days=1)

            self.env['overdraft.line'].sudo().create(lines_to_create)
            record.is_calculated = True

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
            # Create journal entry for accrued interest + penalty
            record._create_interest_journal_entry()
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
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Warning: Close Overdraft'),
            'res_model': 'overdraft.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_overdraft_id': self.id}
        }

    def action_reopen(self):
        for record in self:
            if record.state != 'closed':
                raise UserError(_('Only closed records can be reopened.'))
            record.state = 'approved'

    # -------------------------------------------------------------------------
    # ACCOUNTING METHODS
    # -------------------------------------------------------------------------
    def _create_interest_journal_entry(self):
        """Create a journal entry for accrued interest + penalty."""
        for record in self:
            total = record.total_interest + record.total_penalty
            if total <= 0:
                continue
            if not record.expense_account_id or not record.account_payable_id:
                raise UserError(_(
                    'Please set both Expense Account and Account Payable '
                    'before approving.'
                ))
            partner = record.bank_journal_id.bank_account_id.partner_id \
                if record.bank_journal_id.bank_account_id \
                else record.company_id.partner_id
            move_vals = {
                'journal_id': record.bank_journal_id.id,
                'date': fields.Date.context_today(self),
                'ref': _('Interest accrual: %s') % record.name,
                'overdraft_id': record.id,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _('Interest + Penalty: %s') % record.name,
                        'account_id': record.expense_account_id.id,
                        'debit': total,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Interest Payable: %s') % record.name,
                        'account_id': record.account_payable_id.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': total,
                    }),
                ],
            }
            self.env['account.move'].create(move_vals)

    def action_create_bill(self):
        """Create a vendor bill for interest + penalty."""
        for record in self:
            total = record.total_interest + record.total_penalty
            if total <= 0:
                raise UserError(_('No interest or penalty to bill.'))
            if not record.expense_account_id:
                raise UserError(_('Please set the Expense Account before creating a bill.'))

            partner = record.bank_journal_id.bank_account_id.partner_id \
                if record.bank_journal_id.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', record.company_id.id),
            ], limit=1)
            if not purchase_journal:
                raise UserError(_('No purchase journal found. Please create one in Accounting > Configuration > Journals.'))

            bill_vals = {
                'move_type': 'in_invoice',
                'journal_id': purchase_journal.id,
                'partner_id': partner.id if partner else False,
                'ref': _('Overdraft Interest Bill: %s') % record.name,
                'invoice_date': fields.Date.context_today(self),
                'overdraft_id': record.id,
                'invoice_line_ids': [
                    (0, 0, {
                        'name': _('Overdraft Interest: %s') % record.name,
                        'account_id': record.expense_account_id.id,
                        'quantity': 1,
                        'price_unit': record.total_interest,
                    }),
                ],
            }
            if record.total_penalty > 0:
                bill_vals['invoice_line_ids'].append(
                    (0, 0, {
                        'name': _('Overdraft Penalty: %s') % record.name,
                        'account_id': record.expense_account_id.id,
                        'quantity': 1,
                        'price_unit': record.total_penalty,
                    })
                )
            self.env['account.move'].create(bill_vals)

    # -------------------------------------------------------------------------
    # SMART BUTTON ACTIONS
    # -------------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        moves = self.env['account.move'].search([
            ('overdraft_id', '=', self.id),
            ('move_type', '=', 'entry'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    def action_view_bills(self):
        self.ensure_one()
        bills = self.env['account.move'].search([
            ('overdraft_id', '=', self.id),
            ('move_type', '=', 'in_invoice'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }

    def action_record_payment(self):
        """Open the payment wizard popup."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Payment'),
            'res_model': 'overdraft.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_overdraft_id': self.id,
            },
        }

