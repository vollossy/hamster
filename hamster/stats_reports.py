# - coding: utf-8 -

# Copyright (C) 2008-2009 Toms Bauģis <toms.baugis at gmail.com>

# This file is part of Project Hamster.

# Project Hamster is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Project Hamster is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Project Hamster.  If not, see <http://www.gnu.org/licenses/>.


import pygtk
pygtk.require('2.0')

import os
import gtk, gobject
import pango

import stuff
import charting

from edit_activity import CustomFactController
import reports, graphics

import widgets

from configuration import runtime, GconfStore
import webbrowser

from itertools import groupby
from gettext import ngettext

import datetime as dt
import calendar
import time
from hamster.i18n import C_



class ReportsBox(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)
        self._gui = stuff.load_ui_file("stats_reports.ui")
        self.get_widget("reports_box").reparent(self) #mine!

        self.view_date = dt.date.today()
        
        #set to monday
        self.start_date = self.view_date - \
                                      dt.timedelta(self.view_date.weekday() + 1)
        # look if we need to start on sunday or monday
        self.start_date = self.start_date + \
                                      dt.timedelta(stuff.locale_first_weekday())
        
        self.end_date = self.start_date + dt.timedelta(6)



        self.fact_store = gtk.TreeStore(int, str, str, str, str, str, gobject.TYPE_PYOBJECT) 
        self.setup_tree()
        
        
        #graphs
        self.background = (0.975, 0.975, 0.975)
        self.get_widget("graph_frame").modify_bg(gtk.STATE_NORMAL,
                      gtk.gdk.Color(*[int(b*65536.0) for b in self.background]))


        x_offset = 90 # align all graphs to the left edge
        
        self.category_chart = charting.BarChart(background = self.background,
                                             bar_base_color = (238,221,221),
                                             legend_width = x_offset,
                                             max_bar_width = 35,
                                             show_stack_labels = True
                                             )
        self.get_widget("totals_by_category").add(self.category_chart)
        

        self.day_chart = charting.BarChart(background = self.background,
                                           bar_base_color = (220, 220, 220),
                                           show_scale = True,
                                           max_bar_width = 35,
                                           grid_stride = 4,
                                           legend_width = 20)
        self.get_widget("totals_by_day").add(self.day_chart)


        self.activity_chart = charting.HorizontalBarChart(orient = "horizontal",
                                                   max_bar_width = 25,
                                                   values_on_bars = True,
                                                   stretch_grid = True,
                                                   legend_width = x_offset,
                                                   value_format = "%.1f",
                                                   background = self.background,
                                                   bars_beveled = False,
                                                   animate = False)
        self.get_widget("totals_by_activity").add(self.activity_chart);

        
        
        self.week_view = self.get_widget("reports_week_view")
        self.month_view = self.get_widget("reports_month_view")
        self.month_view.set_group(self.week_view)
        self.day_view = self.get_widget("reports_day_view")
        self.day_view.set_group(self.week_view)
        
        #initiate the form in the week view
        self.week_view.set_active(True)


        runtime.dispatcher.add_handler('activity_updated', self.after_activity_update)
        runtime.dispatcher.add_handler('day_updated', self.after_fact_update)

        selection = self.fact_tree.get_selection()
        selection.connect('changed', self.on_fact_selection_changed,
                          self.fact_store)
        self.popular_categories = [cat[0] for cat in runtime.storage.get_popular_categories()]

        self._gui.connect_signals(self)
        self.fact_tree.grab_focus()

        
        self.config = GconfStore()
        runtime.dispatcher.add_handler('gconf_on_day_start_changed', self.on_day_start_changed)

        self.report_chooser = None
        self.do_graph()

    def setup_tree(self):
        def parent_painter(column, cell, model, iter):
            cell_text = model.get_value(iter, 1)
            if model.iter_parent(iter) is None:
                if model.get_path(iter) == (0,):
                    text = '<span weight="heavy">%s</span>' % cell_text
                else:
                    text = '<span weight="heavy" rise="-20000">%s</span>' % cell_text
                    
                cell.set_property('markup', text)
    
            else:
                activity_name = stuff.escape_pango(cell_text)
                description = stuff.escape_pango(model.get_value(iter, 4))
                category = stuff.escape_pango(model.get_value(iter, 5))

                markup = stuff.format_activity(activity_name,
                                               category,
                                               description,
                                               pad_description = True)            
                cell.set_property('markup', markup)

        def duration_painter(column, cell, model, iter):
            cell.set_property('xalign', 1)
            cell.set_property('yalign', 0)
    

            text = model.get_value(iter, 2)
            if model.iter_parent(iter) is None:
                if model.get_path(iter) == (0,):
                    text = '<span weight="heavy">%s</span>' % text
                else:
                    text = '<span weight="heavy" rise="-20000">%s</span>' % text
            cell.set_property('markup', text)
    

        self.fact_tree = self.get_widget("facts")
        self.fact_tree.set_headers_visible(False)
        self.fact_tree.set_tooltip_column(1)
        self.fact_tree.set_property("show-expanders", False)

        # name
        nameColumn = gtk.TreeViewColumn()
        nameColumn.set_expand(True)
        nameCell = gtk.CellRendererText()
        nameCell.set_property("ellipsize", pango.ELLIPSIZE_END)
        nameColumn.pack_start(nameCell, True)
        nameColumn.set_cell_data_func(nameCell, parent_painter)
        self.fact_tree.append_column(nameColumn)

        # duration
        timeColumn = gtk.TreeViewColumn()
        timeCell = gtk.CellRendererText()
        timeColumn.pack_end(timeCell, True)
        timeColumn.set_cell_data_func(timeCell, duration_painter)




        self.fact_tree.append_column(timeColumn)
        
        self.fact_tree.set_model(self.fact_store)
    
    def on_graph_frame_size_allocate(self, widget, new_size):
        w = min(new_size.width / 4, 200)
        
        self.activity_chart.legend_width = w
        self.category_chart.legend_width = w
        self.get_widget("totals_by_category").set_size_request(w + 40, -1)
    
    def fill_tree(self, facts):
        day_dict = {}
        for day, facts in groupby(facts, lambda fact: fact["date"]):
            day_dict[day] = sorted(list(facts),
                                   key=lambda fact: fact["start_time"])
        
        for i in range((self.end_date - self.start_date).days  + 1):
            current_date = self.start_date + dt.timedelta(i)
            
            # Date format for the label in overview window fact listing
            # Using python datetime formatting syntax. See:
            # http://docs.python.org/library/time.html#time.strftime
            fact_date = current_date.strftime(C_("overview list", "%A, %b %d"))
            
            day_total = dt.timedelta()
            for fact in day_dict.get(current_date, []):
                day_total += fact["delta"]

            day_row = self.fact_store.append(None,
                                             [-1,
                                              fact_date,
                                              stuff.format_duration(day_total),
                                              current_date.strftime('%Y-%m-%d'),
                                              "",
                                              "",
                                              None])

            for fact in day_dict.get(current_date, []):
                self.fact_store.append(day_row,
                                       [fact["id"],
                                        fact["start_time"].strftime('%H:%M') + " " +
                                        fact["name"],
                                        stuff.format_duration(fact["delta"]),
                                        fact["start_time"].strftime('%Y-%m-%d'),
                                        fact["description"],
                                        fact["category"],
                                        fact
                                        ])

        self.fact_tree.expand_all()

        
    def do_charts(self, facts):
        all_categories = self.popular_categories
        
        
        #the single "totals" (by category) bar
        category_sums = stuff.totals(facts, lambda fact: fact["category"],
                      lambda fact: stuff.duration_minutes(fact["delta"]) / 60.0)
        category_totals = [category_sums.get(cat, 0) for cat in all_categories]
        category_keys = ["%s %.1f" % (cat, category_sums.get(cat, 0.0))
                                                      for cat in all_categories]
        self.category_chart.plot([_("Total")],
                                 [category_totals],
                                 stack_keys = category_keys)
        
        # day / category chart
        all_days = [self.start_date + dt.timedelta(i)
                    for i in range((self.end_date - self.start_date).days  + 1)]
        
        by_date_cat = stuff.totals(facts,
                                   lambda fact: (fact["date"], fact["category"]),
                                   lambda fact: stuff.duration_minutes(fact["delta"]) / 60.0)

        res = [[by_date_cat.get((day, cat), 0)
                                 for cat in all_categories] for day in all_days]


        #show days or dates depending on scale
        if (self.end_date - self.start_date).days < 20:
            day_keys = [day.strftime("%a") for day in all_days]
        else:
            # date format used in the overview graph when month view is selected
            # Using python datetime formatting syntax. See:
            # http://docs.python.org/library/time.html#time.strftime
            day_keys = [day.strftime(C_("overview graph", "%b %d"))
                                                            for day in all_days]

        self.day_chart.plot(day_keys, res, stack_keys = all_categories)


        #totals by activity, disguised under a stacked bar chart to get category colors
        activity_sums = stuff.totals(facts,
                                     lambda fact: (fact["name"],
                                                   fact["category"]),
                                     lambda fact: stuff.duration_minutes(fact["delta"]))
        
        #now join activities with same name
        activities = {}
        for key in activity_sums.keys():
            activities.setdefault(key[0], [0.0] * len(all_categories))
            activities[key[0]][all_categories.index(key[1])] = activity_sums[key] / 60.0
            
        by_duration = sorted(activities.items(),
                             key = lambda x: sum(x[1]),
                             reverse = True)
        by_duration_keys = [entry[0] for entry in by_duration]
        
        by_duration = [entry[1] for entry in by_duration]

        self.activity_chart.plot(by_duration_keys,
                                 by_duration,
                                 stack_keys = all_categories)
        

    def set_title(self):
        if self.day_view.get_active():
            # date format for overview label when only single day is visible
            # Using python datetime formatting syntax. See:
            # http://docs.python.org/library/time.html#time.strftime
            start_date_str = self.view_date.strftime(C_("single day overview",
                                                        "%B %d, %Y"))
            # Overview label if looking on single day
            overview_label = _(u"Overview for %(date)s") % \
                                                      ({"date": start_date_str})
        else:
            dates_dict = stuff.dateDict(self.start_date, "start_")
            dates_dict.update(stuff.dateDict(self.end_date, "end_"))
            
            if self.start_date.year != self.end_date.year:
                # overview label if start and end years don't match
                # letter after prefixes (start_, end_) is the one of
                # standard python date formatting ones- you can use all of them
                # see http://docs.python.org/library/time.html#time.strftime
                overview_label = _(u"Overview for %(start_B)s %(start_d)s, %(start_Y)s – %(end_B)s %(end_d)s, %(end_Y)s") % dates_dict
            elif self.start_date.month != self.end_date.month:
                # overview label if start and end month do not match
                # letter after prefixes (start_, end_) is the one of
                # standard python date formatting ones- you can use all of them
                # see http://docs.python.org/library/time.html#time.strftime
                overview_label = _(u"Overview for %(start_B)s %(start_d)s – %(end_B)s %(end_d)s, %(end_Y)s") % dates_dict
            else:
                # overview label for interval in same month
                # letter after prefixes (start_, end_) is the one of
                # standard python date formatting ones- you can use all of them
                # see http://docs.python.org/library/time.html#time.strftime
                overview_label = _(u"Overview for %(start_B)s %(start_d)s – %(end_d)s, %(end_Y)s") % dates_dict

        if self.week_view.get_active():
            dayview_caption = _("Week")
        elif self.month_view.get_active():
            dayview_caption = _("Month")
        else:
            dayview_caption = _("Day")
        
        self.get_widget("overview_label").set_markup("<b>%s</b>" % overview_label)
        self.get_widget("dayview_caption").set_markup("%s" % (dayview_caption))
        

    def do_graph(self):
        self.set_title()
        
        if self.day_view.get_active():
            facts = runtime.storage.get_facts(self.view_date)
        else:
            facts = runtime.storage.get_facts(self.start_date, self.end_date)


        self.get_widget("report_button").set_sensitive(len(facts) > 0)
        self.fact_store.clear()
        
        self.fill_tree(facts)

        if not facts:
            self.get_widget("graphs").hide()
            self.get_widget("no_data_label").show()
            return 


        self.get_widget("no_data_label").hide()
        self.get_widget("graphs").show()
        self.do_charts(facts)
            




    def get_widget(self, name):
        """ skip one variable (huh) """
        return self._gui.get_object(name)




    def after_activity_update(self, widget, renames):
        self.do_graph()
    
    def after_fact_update(self, event, date):
        self.stat_facts = runtime.storage.get_facts(dt.date(1970, 1, 1), dt.date.today())
        self.popular_categories = [cat[0] for cat in runtime.storage.get_popular_categories()]
        
        if self.get_widget("pages").get_current_page() == 0:
            self.do_graph()
        else:
            self.stats()
        
    def on_fact_selection_changed(self, selection, model):
        """ enables and disables action buttons depending on selected item """
        (model, iter) = selection.get_selected()

        id = -1
        if iter:
            id = model[iter][0]

        self.get_widget('remove').set_sensitive(id != -1)
        self.get_widget('edit').set_sensitive(id != -1)

        return True

    def on_facts_row_activated(self, tree, path, column):
        selection = tree.get_selection()
        (model, iter) = selection.get_selected()
        custom_fact = CustomFactController(self, None, model[iter][0])
        custom_fact.show()
        
    def on_add_clicked(self, button):
        selection = self.fact_tree.get_selection()
        (model, iter) = selection.get_selected()

        selected_date = self.view_date
        if iter:
            selected_date = model[iter][3].split("-")
            selected_date = dt.date(int(selected_date[0]),
                                    int(selected_date[1]),
                                    int(selected_date[2]))

        custom_fact = CustomFactController(self, selected_date)
        custom_fact.show()

    def on_prev_clicked(self, button):
        if self.day_view.get_active():
            self.view_date -= dt.timedelta(1)
            if self.view_date < self.start_date:
                self.start_date -= dt.timedelta(7)
                self.end_date -= dt.timedelta(7)
        else:
            if self.week_view.get_active():
                self.start_date -= dt.timedelta(7)
                self.end_date -= dt.timedelta(7)
            
            elif self.month_view.get_active():
                self.end_date = self.start_date - dt.timedelta(1)
                first_weekday, days_in_month = calendar.monthrange(self.end_date.year, self.end_date.month)
                self.start_date = self.end_date - dt.timedelta(days_in_month - 1)

            self.view_date = self.start_date

        self.do_graph()

    def on_next_clicked(self, button):
        if self.day_view.get_active():
            self.view_date += dt.timedelta(1)
            if self.view_date > self.end_date:
                self.start_date += dt.timedelta(7)
                self.end_date += dt.timedelta(7)
        else:
            if self.week_view.get_active():
                self.start_date += dt.timedelta(7)
                self.end_date += dt.timedelta(7)        
            elif self.month_view.get_active():
                self.start_date = self.end_date + dt.timedelta(1)
                first_weekday, days_in_month = calendar.monthrange(self.start_date.year, self.start_date.month)
                self.end_date = self.start_date + dt.timedelta(days_in_month - 1)
        
            self.view_date = self.start_date

        self.do_graph()
    
    def on_home_clicked(self, button):
        self.view_date = dt.date.today()
        if self.week_view.get_active():
            self.start_date = self.view_date - dt.timedelta(self.view_date.weekday() + 1)
            self.start_date = self.start_date + dt.timedelta(stuff.locale_first_weekday())
            self.end_date = self.start_date + dt.timedelta(6)
        
        elif self.month_view.get_active():
            self.start_date = self.view_date - dt.timedelta(self.view_date.day - 1) #set to beginning of month
            first_weekday, days_in_month = calendar.monthrange(self.view_date.year, self.view_date.month)
            self.end_date = self.start_date + dt.timedelta(days_in_month - 1)
        
        self.do_graph()
        
    def on_day_toggled(self, button):
        self.start_date = self.view_date - dt.timedelta(self.view_date.weekday() + 1)
        self.start_date = self.start_date + dt.timedelta(stuff.locale_first_weekday())
        self.end_date = self.start_date + dt.timedelta(6)
        
        self.get_widget("prev").set_tooltip_text(_("Previous day"))
        self.get_widget("next").set_tooltip_text(_("Next day"))
        self.get_widget("home").set_tooltip_text(_("Today"))
        self.get_widget("home").set_label(_("Today"))
        
        self.do_graph()

    def on_week_toggled(self, button):
        self.start_date = self.view_date - dt.timedelta(self.view_date.weekday() + 1)
        self.start_date = self.start_date + dt.timedelta(stuff.locale_first_weekday())
        self.end_date = self.start_date + dt.timedelta(6)

        self.get_widget("prev").set_tooltip_text(_("Previous week"))
        self.get_widget("next").set_tooltip_text(_("Next week"))
        self.get_widget("home").set_tooltip_text(_("This week"))
        self.get_widget("home").set_label(_("This Week"))
        self.do_graph()

        
    def on_month_toggled(self, button):
        self.start_date = self.view_date - dt.timedelta(self.view_date.day - 1) #set to beginning of month
        first_weekday, days_in_month = calendar.monthrange(self.view_date.year, self.view_date.month)
        self.end_date = self.start_date + dt.timedelta(days_in_month - 1)

        self.get_widget("prev").set_tooltip_text(_("Previous month"))
        self.get_widget("next").set_tooltip_text(_("Next month"))
        self.get_widget("home").set_tooltip_text(_("This month"))
        self.get_widget("home").set_label(_("This Month"))
        self.do_graph()
        
        
    def init_report_dialog(self):
        chooser = self.get_widget('save_report_dialog')
        chooser.set_action(gtk.FILE_CHOOSER_ACTION_SAVE)
        """
        chooser.set
        
        chooser = gtk.FileChooserDialog(title = _("Save report - Time Tracker"),
                                        parent = None,
                                        buttons=(gtk.STOCK_CANCEL,
                                                 gtk.RESPONSE_CANCEL,
                                                 gtk.STOCK_SAVE,
                                                 gtk.RESPONSE_OK))
        """
        chooser.set_current_folder(os.path.expanduser("~"))

        filters = {}

        filter = gtk.FileFilter()
        filter.set_name(_("HTML Report"))
        filter.add_mime_type("text/html")
        filter.add_pattern("*.html")
        filter.add_pattern("*.htm")
        filters[filter] = "html"
        chooser.add_filter(filter)

        filter = gtk.FileFilter()
        filter.set_name(_("Tab-Separated Values (TSV)"))
        filter.add_mime_type("text/plain")
        filter.add_pattern("*.tsv")
        filter.add_pattern("*.txt")
        filters[filter] = "tsv"
        chooser.add_filter(filter)

        filter = gtk.FileFilter()
        filter.set_name(_("XML"))
        filter.add_mime_type("text/xml")
        filter.add_pattern("*.xml")
        filters[filter] = "xml"
        chooser.add_filter(filter)

        filter = gtk.FileFilter()
        filter.set_name(_("iCal"))
        filter.add_mime_type("text/calendar")
        filter.add_pattern("*.ics")
        filters[filter] = "ical"
        chooser.add_filter(filter)

        filter = gtk.FileFilter()
        filter.set_name("All files")
        filter.add_pattern("*")
        chooser.add_filter(filter)
        
    def on_report_chosen(self, widget, format, path, start_date, end_date,
                                                                    categories):
        self.report_chooser = None
        
        facts = runtime.storage.get_facts(start_date, end_date, category_id = categories)
        reports.simple(facts,
                       start_date,
                       end_date,
                       format,
                       path)

        if format == ("html"):
            webbrowser.open_new("file://%s" % path)
        else:
            gtk.show_uri(gtk.gdk.Screen(),
                         "file://%s" % os.path.split(path)[0], 0L)

    def on_report_chooser_closed(self, widget):
        self.report_chooser = None
        
    def on_report_button_clicked(self, widget):
        if not self.report_chooser:
            self.report_chooser = widgets.ReportChooserDialog()
            self.report_chooser.connect("report-chosen", self.on_report_chosen)
            self.report_chooser.connect("report-chooser-closed",
                                        self.on_report_chooser_closed)
            self.report_chooser.show(self.start_date, self.end_date)
        else:
            self.report_chooser.present()
        
        
    def on_day_start_changed(self, event, new_minutes):
        self.do_graph()

