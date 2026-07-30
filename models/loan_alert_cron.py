import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class LoanAlertCron(models.AbstractModel):
    _name = 'loan.alert.cron'
    _description = 'Loan Alert Cron Scheduler'

    @api.model
    def _cron_send_weekly_payment_alert(self):
        """
        Scheduled action to send a weekly summary of payments needed to be made
        for this week and unpaid amounts belonging to term, preshipment and merchandise loans.
        Runs every Monday at 8 AM.
        """
        today = fields.Date.context_today(self)
        start_of_week = today
        end_of_week = today + timedelta(days=6)

        overdue_items = []
        due_this_week_items = []

        # Helper function to format money
        def format_amount(amount, currency):
            if currency:
                return f"{currency.symbol} {amount:,.2f}" if currency.position == 'before' else f"{amount:,.2f} {currency.symbol}"
            return f"{amount:,.2f}"

        # 1. Term Loan (Term Loan Line)
        term_lines = self.env['term.loan.line'].sudo().search([
            ('loan_id.state', '=', 'active'),
            ('is_paid', '=', False),
        ])
        for line in term_lines:
            if line.payment_date:
                amount_str = format_amount(line.total_payment, line.currency_id)
                item = {
                    'loan_name': line.loan_id.name,
                    'type': 'Term Loan',
                    'amount': amount_str,
                    'due_date': line.payment_date,
                    'model': 'term.loan',
                    'id': line.loan_id.id,
                    'days_past_due': max(0, (today - line.payment_date).days),
                    'penalty_amount': format_amount(line.penalty_amount, line.currency_id),
                }
                if line.payment_date < start_of_week:
                    overdue_items.append(item)
                elif start_of_week <= line.payment_date <= end_of_week:
                    due_this_week_items.append(item)

        # 2. Pre-Shipment Loan
        preshipment_loans = self.env['preshipment.loan'].sudo().search([
            ('state', '=', 'active'),
        ]).filtered(lambda l: l.outstanding_balance > 0)
        for loan in preshipment_loans:
            if loan.end_date:
                amount_str = format_amount(loan.outstanding_balance, loan.currency_id)
                item = {
                    'loan_name': loan.name,
                    'type': 'Pre-Shipment Loan',
                    'amount': amount_str,
                    'due_date': loan.end_date,
                    'model': 'preshipment.loan',
                    'id': loan.id,
                    'days_past_due': max(0, (today - loan.end_date).days),
                    'penalty_amount': format_amount(loan.penalty_amount, loan.currency_id),
                }
                if loan.end_date < start_of_week:
                    overdue_items.append(item)
                elif start_of_week <= loan.end_date <= end_of_week:
                    due_this_week_items.append(item)

        # 3. Merchandise Loan
        merchandise_loans = self.env['merchandise.loan'].sudo().search([
            ('state', '=', 'active'),
        ]).filtered(lambda l: l.outstanding_loan > 0)
        for loan in merchandise_loans:
            if loan.date_to:
                amount_str = format_amount(loan.outstanding_loan, loan.currency_id)
                item = {
                    'loan_name': loan.name,
                    'type': 'Merchandise Loan',
                    'amount': amount_str,
                    'due_date': loan.date_to,
                    'model': 'merchandise.loan',
                    'id': loan.id,
                    'days_past_due': max(0, (today - loan.date_to).days),
                    'penalty_amount': format_amount(loan.penalty_amount, loan.currency_id),
                }
                if loan.date_to < start_of_week:
                    overdue_items.append(item)
                elif start_of_week <= loan.date_to <= end_of_week:
                    due_this_week_items.append(item)

        _logger.info(f"CRON: Overdue items: {len(overdue_items)}, Due this week items: {len(due_this_week_items)}")

        # Prepare message body in plain text
        body_text = "Weekly Loan Payment Summary\n"
        body_text += f"Here is your weekly summary of upcoming and unpaid loan payments as of {today.strftime('%Y-%m-%d')}:\n\n"

        if overdue_items:
            body_text += "⚠️ Overdue / Unpaid Amounts:\n"
            for item in overdue_items:
                body_text += f"• {item['loan_name']} ({item['type']}): {item['amount']} (Original Due Date: {item['due_date'].strftime('%Y-%m-%d')})\n"
            body_text += "\n"

        if due_this_week_items:
            body_text += "📅 Due This Week:\n"
            for item in due_this_week_items:
                body_text += f"• {item['loan_name']} ({item['type']}): {item['amount']} (Due Date: {item['due_date'].strftime('%Y-%m-%d')})\n"
            body_text += "\n"

        if not overdue_items and not due_this_week_items:
            body_text += "✔ All Clear: No upcoming or overdue loan payments found for this week.\n\n"

        body_text += "This is an automated notification. Please ensure payments are processed on time."

        # Prepare HTML body for the report
        html_body = f"""
        <div style="font-family: Arial, sans-serif;">
            <h3 style="color: #2c3e50;">Weekly Loan Payment Summary</h3>
            <p style="color: #555;">Here is your weekly summary of upcoming and unpaid loan payments as of <strong>{today.strftime('%Y-%m-%d')}</strong>:</p>
        """

        def make_link(model, res_id, name):
            return f"<a href='/web#id={res_id}&model={model}&view_type=form' target='_blank' style='text-decoration: none; font-weight: bold; color: #007bff;'>{name}</a>"

        def build_table(items, title, is_overdue=False):
            if not items:
                return ""
            color = "#dc3545" if is_overdue else "#28a745"
            table_html = f"""
            <h4 style="color: {color}; margin-top: 20px;">{title}</h4>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                <thead>
                    <tr style="background-color: #f8f9fa; border-bottom: 2px solid #dee2e6;">
                        <th style="padding: 10px; text-align: left; border: 1px solid #dee2e6;">Loan</th>
                        <th style="padding: 10px; text-align: left; border: 1px solid #dee2e6;">Type</th>
                        <th style="padding: 10px; text-align: right; border: 1px solid #dee2e6;">Amount</th>
                        <th style="padding: 10px; text-align: right; border: 1px solid #dee2e6;">Due Date</th>
                        <th style="padding: 10px; text-align: right; border: 1px solid #dee2e6;">Days Past Due</th>
                        <th style="padding: 10px; text-align: right; border: 1px solid #dee2e6;">Penalty</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in items:
                link = make_link(item['model'], item['id'], item['loan_name'])
                due_date_str = item['due_date'].strftime('%Y-%m-%d')
                days_str = str(item['days_past_due']) if item['days_past_due'] > 0 else "-"
                penalty_str = item['penalty_amount'] if item['days_past_due'] > 0 else "-"
                
                table_html += f"""
                    <tr style="border-bottom: 1px solid #e9ecef;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;">{link}</td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #495057;">{item['type']}</td>
                        <td style="padding: 10px; text-align: right; border: 1px solid #dee2e6; font-weight: bold;">{item['amount']}</td>
                        <td style="padding: 10px; text-align: right; border: 1px solid #dee2e6; color: {color};">{due_date_str}</td>
                        <td style="padding: 10px; text-align: right; border: 1px solid #dee2e6; color: #dc3545;">{days_str}</td>
                        <td style="padding: 10px; text-align: right; border: 1px solid #dee2e6; color: #dc3545;">{penalty_str}</td>
                    </tr>
                """
            table_html += """
                </tbody>
            </table>
            """
            return table_html

        if overdue_items:
            html_body += build_table(overdue_items, "⚠️ Overdue / Unpaid Amounts", True)

        if due_this_week_items:
            html_body += build_table(due_this_week_items, "📅 Due This Week", False)

        if not overdue_items and not due_this_week_items:
            html_body += """
            <div style="padding: 15px; background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; border-radius: 4px; margin-top: 15px;">
                <strong>✔ All Clear:</strong> No upcoming or overdue loan payments found for this week.
            </div>
            """

        html_body += """
            <p style="margin-top: 20px; color: #6c757d; font-size: 0.9em;">
                This is an automated notification. Please ensure payments are processed on time.
            </p>
        </div>
        """

        # Create the report record using sudo to avoid permission issues
        report = self.env['loan.management.report'].sudo().create({
            'name': f"Weekly Report - {today.strftime('%Y-%m-%d')}",
            'date': today,
            'report_body': html_body,
        })

        # Find users who are in Loan Management user group
        group_user = self.env.ref('overdraft_interest_calculator.group_overdraft_viewer', raise_if_not_found=False)
        if group_user:
            users = group_user.users
            _logger.info(f"CRON: Found {len(users)} users in overdraft_interest_calculator.group_overdraft_viewer")
        else:
            users = self.env.ref('base.group_system').users
            _logger.info(f"CRON: Found {len(users)} users in base.group_system (group_overdraft_viewer not found)")

        partners = users.mapped('partner_id')
        _logger.info(f"CRON: Partners to notify: {partners.ids}")
        if partners:
            odoobot = self.env.ref('base.partner_root')
            sys_user = self.env.ref('base.user_root')
            for partner in partners:
                try:
                    # Get or create a direct chat channel between OdooBot and the user
                    channel = self.env['discuss.channel'].with_user(sys_user).sudo().channel_get([partner.id])
                    if channel:
                        channel.sudo().message_post(
                            body=body_text,
                            message_type="comment",
                            subtype_xmlid="mail.mt_comment",
                            author_id=odoobot.id,
                        )
                except Exception as e:
                    _logger.warning(f"CRON: Failed to post message to discuss.channel for partner {partner.id}: {e}")
            _logger.info("CRON: message_post called on discuss.channel for users.")
        else:
            _logger.warning("CRON: No partners to notify.")

        # Create activities for users using sudo
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        activity_type_id = activity_type.id if activity_type else 4

        for user in users:
            try:
                self.env['mail.activity'].sudo().create({
                    'res_id': report.id,
                    'res_model_id': self.env['ir.model']._get_id('loan.management.report'),
                    'activity_type_id': activity_type_id,
                    'summary': 'Weekly Loan Payment Summary',
                    'note': 'Please review the weekly loan payment summary. Click to open.',
                    'user_id': user.id,
                    'date_deadline': today,
                })
            except Exception as e:
                _logger.warning(f"CRON: Failed to create activity for user {user.id}: {e}")
        _logger.info(f"CRON: Created activities for {len(users)} users.")
