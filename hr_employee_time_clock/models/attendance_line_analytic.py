# -*- coding: utf-8 -*-

##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2016 - now Bytebrand Outsourcing AG (<http://www.bytebrand.net>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from datetime import datetime, date
from odoo import api, fields, models, _
import logging
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from dateutil import rrule, parser

_logger = logging.getLogger(__name__)


class AttendanceLineAnalytic(models.Model):
    _name = "attendance.line.analytic"
    _order = "name"

    name = fields.Date(string='Date')
    sheet_id = fields.Many2one('hr_timesheet_sheet.sheet',
                               string='Sheet',
                               index=True)
    attendance_ids = fields.One2many('hr.attendance',
                                     'attendance_line_analytic_id',
                                     string='Attendance IDS',
                                     readonly=True, )
    contract_id = fields.Many2one('hr.contract',
                                  string='Contract')
    duty_hours = fields.Float(string='Duty Hours',
                              default=0.0)
    worked_hours = fields.Float(string='Worked Hours',
                                default=0.0)
    bonus_worked_hours = fields.Float(string='Bonus Worked Hours',
                                      default=0.0)
    night_shift_worked_hours = fields.Float(string='Night Shift',
                                            default=0.0)
    difference = fields.Float(compute='_get_difference',
                              string='Difference',
                              default=0.0)
    running = fields.Float(string='Running',
                           default=0.0)
    leave_description = fields.Char(string='Leave Description',
                                    default='-', )
    day_checked = fields.Boolean(string='Checked',
                                 default=False)

    @api.model
    def calculate_wrong_date(self):
        analytic_lines = self.search([('day_checked', '=', False)])
        for line in analytic_lines:
            time1 = '{} 00:00:00'.format(line.name)
            t1 = datetime.strptime(time1, "%Y-%m-%d %H:%M:%S").date()
            if (line.difference < -4.0 or line.difference > 4.0) \
                    and date.today() > t1:
                ir_model_data = self.env['ir.model.data']
                template_id = ir_model_data.get_object_reference(
                    'hr_employee_time_clock_notification',
                    'email_template_fail_check_out_'
                    'notification')
                if template_id:
                    mail_template = self.env['mail.template'].browse(
                        template_id[1])
                    mail_template.send_mail(res_id=line.id, force_send=True)
            line.day_checked = True

    @api.multi
    def recalculate_line(self, line_date, employee_id=None):
        if employee_id:
            lines = self.search([('name', '=', line_date),
                                 ('sheet_id.employee_id', '=', employee_id.id)])
            date_line = line_date
        else:
            lines = self.search([('name', '=', line_date)])
            date_line = list(rrule.rrule(rrule.DAILY,
                                         dtstart=parser.parse(line_date),
                                         until=parser.parse(line_date)))[0]
        for line in lines:
            duty_hours, contract, leave, public_holiday = \
                self.calculate_duty_hours(sheet=line.sheet_id,
                                          date_from=date_line)
            values = {'duty_hours': duty_hours,
                      'contract_id': contract.id,
                      'leave_description': '-'}
            if public_holiday:
                values.update(leave_description=public_holiday.name)
            if leave and leave[0]:
                values.update(leave_description=leave[0].name)
            line.write(values)

    @api.multi
    def _get_difference(self):
        self.difference = self.worked_hours - self.duty_hours

    @api.multi
    def recalculate_line_worktime(self, new_attendance, values):
        if values.get('check_in') or values.get('check_out'):
            check_in = values.get('check_in') or new_attendance.check_in
            check_out = values.get('check_out') or new_attendance.check_out
            name = new_attendance.check_in.split(' ')[0]

            line = self.search([('name', '=', name),
                                ('sheet_id', '=', new_attendance.sheet_id.id)])

            time1 = '{} 00:00:00'.format(name)

            t1 = datetime.strptime(time1, "%Y-%m-%d %H:%M:%S")
            duty_hours = new_attendance.sheet_id.calculate_duty_hours(
                t1,
                {'date_to': new_attendance.sheet_id.date_to,
                 'date_from': new_attendance.sheet_id.date_from, })
            if not line:
                line = self.create({'name': name,
                                    'sheet_id': new_attendance.sheet_id.id,
                                    'duty_hours': duty_hours})
                new_attendance.attendance_line_analytic_id = line.id
            else:
                if not new_attendance.attendance_line_analytic_id:
                    new_attendance.attendance_line_analytic_id = line.id

            if check_out:
                worked_hours = 0
                bonus_worked_hours = 0
                night_shift_worked_hours = 0
                for attendance in line.attendance_ids:
                    bonus_worked_hours += attendance.bonus_worked_hours
                    night_shift_worked_hours \
                        += attendance.night_shift_worked_hours
                    if attendance.id != new_attendance.id:
                        worked_hours += attendance.worked_hours

                    else:
                        delta = datetime.strptime(
                            check_out, DEFAULT_SERVER_DATETIME_FORMAT) - \
                                datetime.strptime(
                                    check_in, DEFAULT_SERVER_DATETIME_FORMAT)
                        worked_hours += delta.total_seconds() / 3600.0

                line.write({
                    'duty_hours': duty_hours,
                    'worked_hours': worked_hours,
                    'day_checked': False,
                    'bonus_worked_hours': bonus_worked_hours,
                    'night_shift_worked_hours': night_shift_worked_hours,
                })

    @api.multi
    def create_line(self, sheet, date_from, date_to):
        dates = list(rrule.rrule(rrule.DAILY,
                                 dtstart=parser.parse(date_from),
                                 until=parser.parse(date_to)))

        for date_line in dates:
            name = str(date_line).split(' ')[0]
            line = self.search(
                [('name', '=', name),
                 ('sheet_id', '=', sheet.id)])
            if not line:

                duty_hours, contract, leave, public_holiday = \
                    self.calculate_duty_hours(sheet=sheet,
                                              date_from=date_line)
                print(
                    '\n duty_hours, contract, leave, public_holiday >>>>>> %s' % duty_hours,
                    contract, leave, public_holiday)
                if leave[0]:
                    duty_hours -= duty_hours * leave[1]
                if contract and contract.rate_per_hour:
                    duty_hours = 0.0
                values = {'name': name,
                          'sheet_id': sheet.id,
                          'duty_hours': duty_hours,
                          'contract_id': contract.id}
                if public_holiday:
                    values.update(leave_description=public_holiday.name)
                if leave and leave[0]:
                    values.update(leave_description=leave[0].name)
                self.create(values)

    @api.multi
    def calculate_duty_hours(self, sheet, date_from):
        contract_obj = self.env['hr.contract']
        calendar_obj = self.env['resource.calendar']
        duty_hours = 0.0
        contract = contract_obj.search(
            [('state', '!=', 'cancel'),
             ('employee_id', '=', sheet.employee_id.id),
             ('date_start', '<=', date_from), '|',
             ('date_end', '>=', date_from),
             ('date_end', '=', None)])

        if len(contract) > 1:
            raise
        leave = sheet.count_leaves(date_from, sheet.employee_id.id)
        public_holiday = sheet.count_public_holiday(date_from)
        if contract and contract.rate_per_hour:
            return 0.00, contract, leave, public_holiday
        ctx = dict(self.env.context).copy()
        # ctx.update(period)
        dh = calendar_obj.get_working_hours_of_date(
            cr=self._cr,
            uid=self.env.user.id,
            ids=contract.resource_calendar_id.id,
            start_dt=date_from,
            resource_id=sheet.employee_id.id,
            context=ctx)

        if contract.state != 'cancel':
            if leave[1] == 0 and not public_holiday:
                if not dh:
                    dh = 0.00
                duty_hours += dh
            elif public_holiday:
                dh = 0.00
                duty_hours += dh
            else:
                if not public_holiday and leave[1] != 0:
                    duty_hours += dh * (1 - leave[1])
        else:
            dh = 0.00
            duty_hours += dh
        return duty_hours, contract, leave, public_holiday