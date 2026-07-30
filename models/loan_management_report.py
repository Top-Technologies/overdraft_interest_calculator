from odoo import models, fields, api
from odoo.exceptions import UserError

class LoanManagementReport(models.Model):
    _name = 'loan.management.report'
    _description = 'Loan Management Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Report Name', required=True, default='Weekly Report')
    date = fields.Date(string='Date', default=fields.Date.context_today)
    report_body = fields.Html(string='Report Body', readonly=True)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, f"{record.name} - {record.date}"))
        return result

    def action_print_report(self):
        return self.env.ref('overdraft_interest_calculator.action_report_loan_management_report').report_action(self)

    def _extract_table_data(self):
        """Extract sections and rows from report_body HTML."""
        if not self.report_body:
            return []
        try:
            import bs4
        except ImportError:
            raise UserError('The beautifulsoup4 library is required. Please install it: pip install beautifulsoup4')
        soup = bs4.BeautifulSoup(self.report_body, 'html.parser')
        data = []
        
        elements = soup.find_all(['h4', 'table'])
        current_section = "Weekly Summary"
        
        for el in elements:
            if el.name == 'h4':
                current_section = el.get_text(strip=True)
            elif el.name == 'table':
                headers = [th.get_text(strip=True) for th in el.find_all('th')]
                rows = []
                for tr in el.find_all('tr'):
                    tds = [td.get_text(strip=True) for td in tr.find_all('td')]
                    if tds:
                        rows.append(tds)
                data.append({
                    'section': current_section,
                    'headers': headers,
                    'rows': rows
                })
        return data

    def action_export_xlsx(self):
        self.ensure_one()
        import io, base64, xlsxwriter
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Weekly Report')

        title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'color': '#2c3e50'})
        section_fmt = workbook.add_format({'bold': True, 'font_size': 11, 'bg_color': '#e9ecef', 'border': 1})
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#f8f9fa', 'border': 1})
        cell_fmt = workbook.add_format({'border': 1})

        row_idx = 0
        worksheet.write(row_idx, 0, f"{self.name} ({self.date})", title_fmt)
        row_idx += 2

        tables = self._extract_table_data()
        for t in tables:
            worksheet.write(row_idx, 0, t['section'], section_fmt)
            row_idx += 1
            
            for col_idx, h in enumerate(t['headers']):
                worksheet.write(row_idx, col_idx, h, header_fmt)
            row_idx += 1
            
            for r in t['rows']:
                for col_idx, val in enumerate(r):
                    worksheet.write(row_idx, col_idx, val, cell_fmt)
                row_idx += 1
            row_idx += 1

        workbook.close()
        output.seek(0)
        
        attachment = self.env['ir.attachment'].create({
            'name': f"{self.name}_{self.date}.xlsx",
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_export_csv(self):
        self.ensure_one()
        import io, base64, csv
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([f"{self.name} ({self.date})"])
        writer.writerow([])

        tables = self._extract_table_data()
        for t in tables:
            writer.writerow([t['section']])
            if t['headers']:
                writer.writerow(t['headers'])
            for r in t['rows']:
                writer.writerow(r)
            writer.writerow([])

        attachment = self.env['ir.attachment'].create({
            'name': f"{self.name}_{self.date}.csv",
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue().encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/csv',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

