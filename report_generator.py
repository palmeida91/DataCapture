"""
OEE Weekly Report Generator
Queries PostgreSQL, generates charts with matplotlib, builds PDF with reportlab,
and optionally sends via Gmail SMTP.

Usage:
    # Generate PDF only (defaults to previous week)
    python3.12 report_generator.py

    # Specify week
    python3.12 report_generator.py --week-of 2026-02-03

    # Generate and send email
    python3.12 report_generator.py --email

    # Custom date range
    python3.12 report_generator.py --from 2026-02-03 --to 2026-02-09

Dependencies (install on laptop):
    pip3.12 install matplotlib reportlab psycopg2-binary --break-system-packages
"""

import os
import sys
import json
import argparse
import smtplib
import tempfile
from pathlib import Path
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: Missing psycopg2. Install with:")
    print("  pip3.12 install psycopg2-binary --break-system-packages")
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use('Agg')  # Headless rendering, no display needed
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.patches import FancyBboxPatch
except ImportError:
    print("ERROR: Missing matplotlib. Install with:")
    print("  pip3.12 install matplotlib --break-system-packages")
    sys.exit(1)

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm, cm
    from reportlab.lib.colors import HexColor, black, white, grey
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak,
        Table, TableStyle, Image, KeepTogether
    )
except ImportError:
    print("ERROR: Missing reportlab. Install with:")
    print("  pip3.12 install reportlab --break-system-packages")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================
# Load database config from collector_config.json if available
CONFIG_PATH = Path(__file__).parent / "config" / "collector_config.json"

def load_db_config():
    """Load database connection from collector_config.json"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        db = config['database']
        return {
            'host': db['host'],
            'port': db['port'],
            'dbname': db['database'],
            'user': db['user'],
            'password': db['password']
        }
    else:
        # Fallback defaults
        return {
            'host': 'localhost',
            'port': 5432,
            'dbname': 'production',
            'user': 'collector',
            'password': 'iRob1'
        }

# Email configuration
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender': 'irobreport@gmail.com',
    'password': '',  # Set via --smtp-password or REPORT_EMAIL_PASSWORD env var
    'recipients': ['irobreport@gmail.com'],
}

# Shift definitions (must match collector_config.json)
SHIFTS = {
    'monday_to_thursday': {
        1: {'start': '06:00', 'end': '14:00'},
        2: {'start': '14:00', 'end': '22:00'},
        3: {'start': '22:00', 'end': '06:00'},
    },
    'friday': {
        1: {'start': '06:00', 'end': '13:30'},
        2: {'start': '13:30', 'end': '21:00'},
        3: {'start': '21:00', 'end': '04:30'},
    }
}

# Chart colours
COLORS = {
    'oee_good': '#2ecc71',      # Green
    'oee_warning': '#f1c40f',   # Yellow
    'oee_bad': '#e74c3c',       # Red
    'fault': '#e74c3c',         # Red
    'blocked': '#f39c12',       # Orange
    'starved': '#3498db',       # Blue
    'bar_fill': '#2980b9',      # Default bar blue
    'header_bg': '#2c3e50',     # Dark header
    'row_alt': '#ecf0f1',       # Alternating row grey
}

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


# =============================================================================
# DATABASE QUERIES
# =============================================================================
class ReportDataFetcher:
    """Fetches all data needed for the weekly report"""

    def __init__(self, db_config):
        self.conn = psycopg2.connect(**db_config)
        self.conn.autocommit = True
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self):
        self.cursor.close()
        self.conn.close()

    def get_oee_per_station_per_shift(self, date_from, date_to, day_of_week, shift_number):
        """
        Get OEE per station for a specific day-of-week and shift.
        Uses PERCENTILE_CONT (median) for performance, AVG for TA.
        Returns list of dicts with sequence_name, availability, performance, oee.
        """
        # Determine shift time boundaries
        is_friday = (day_of_week == 5)
        shift_key = 'friday' if is_friday else 'monday_to_thursday'
        shift_def = SHIFTS[shift_key][shift_number]
        start_time = shift_def['start']
        end_time = shift_def['end']

        self.cursor.execute("""
            WITH shift_boundaries AS (
                -- Generate all dates in range for this day of week
                SELECT d::date as shift_date
                FROM generate_series(%s::date, %s::date, '1 day') d
                WHERE EXTRACT(ISODOW FROM d) = %s
            ),
            station_cycles AS (
                SELECT
                    ct.sequence_id,
                    s.sequence_name,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ct.cycle_time_seconds)
                        AS median_cycle_sec,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ct.desired_cycle_time_seconds)
                        AS median_desired_sec
                FROM cycle_times ct
                JOIN sequences s ON ct.sequence_id = s.sequence_id
                CROSS JOIN shift_boundaries sb
                WHERE s.is_active = true
                    AND CASE
                        WHEN %s >= %s THEN
                            -- Normal shift (e.g. 06:00-14:00)
                            ct.time >= (sb.shift_date + %s::time)
                            AND ct.time < (sb.shift_date + %s::time)
                        ELSE
                            -- Overnight shift (e.g. 22:00-06:00)
                            ct.time >= (sb.shift_date + %s::time)
                            OR ct.time < (sb.shift_date + interval '1 day' + %s::time)
                    END
                GROUP BY ct.sequence_id, s.sequence_name
            ),
            station_ta AS (
                SELECT
                    ta.sequence_id,
                    AVG(ta.ta_percent) AS avg_ta
                FROM technical_availability ta
                JOIN sequences s ON ta.sequence_id = s.sequence_id
                CROSS JOIN shift_boundaries sb
                WHERE s.is_active = true
                    AND CASE
                        WHEN %s >= %s THEN
                            ta.time >= (sb.shift_date + %s::time)
                            AND ta.time < (sb.shift_date + %s::time)
                        ELSE
                            ta.time >= (sb.shift_date + %s::time)
                            OR ta.time < (sb.shift_date + interval '1 day' + %s::time)
                    END
                GROUP BY ta.sequence_id
            )
            SELECT
                sc.sequence_name,
                COALESCE(ROUND(COALESCE(sta.avg_ta, 0)::numeric, 1), 0) AS availability,
                COALESCE(ROUND(CASE
                    WHEN sc.median_cycle_sec > 0 THEN
                        (sc.median_desired_sec / sc.median_cycle_sec * 100)
                    ELSE 0
                END::numeric, 1), 0) AS performance,
                COALESCE(ROUND((
                    COALESCE(sta.avg_ta, 0) / 100.0 *
                    CASE
                        WHEN sc.median_cycle_sec > 0 THEN
                            sc.median_desired_sec / sc.median_cycle_sec
                        ELSE 0
                    END * 100
                )::numeric, 1), 0) AS oee
            FROM station_cycles sc
            LEFT JOIN station_ta sta ON sc.sequence_id = sta.sequence_id
            ORDER BY sc.sequence_name
        """, (
            date_from, date_to, day_of_week,
            # station_cycles WHERE
            end_time, start_time,
            start_time, end_time,
            start_time, end_time,
            # station_ta WHERE
            end_time, start_time,
            start_time, end_time,
            start_time, end_time,
        ))

        return self.cursor.fetchall()

    def get_downtime_per_station_per_shift(self, date_from, date_to, day_of_week, shift_number):
        """Get median downtime breakdown per station for a shift"""
        is_friday = (day_of_week == 5)
        shift_key = 'friday' if is_friday else 'monday_to_thursday'
        shift_def = SHIFTS[shift_key][shift_number]
        start_time = shift_def['start']
        end_time = shift_def['end']

        self.cursor.execute("""
            WITH shift_boundaries AS (
                SELECT d::date as shift_date
                FROM generate_series(%s::date, %s::date, '1 day') d
                WHERE EXTRACT(ISODOW FROM d) = %s
            )
            SELECT
                s.sequence_name,
                COALESCE(ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY ta.fault_time_seconds)::numeric, 0), 0) AS fault_sec,
                COALESCE(ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY ta.blocked_time_seconds)::numeric, 0), 0) AS blocked_sec,
                COALESCE(ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY ta.starved_time_seconds)::numeric, 0), 0) AS starved_sec
            FROM technical_availability ta
            JOIN sequences s ON ta.sequence_id = s.sequence_id
            CROSS JOIN shift_boundaries sb
            WHERE s.is_active = true
                AND CASE
                    WHEN %s >= %s THEN
                        ta.time >= (sb.shift_date + %s::time)
                        AND ta.time < (sb.shift_date + %s::time)
                    ELSE
                        ta.time >= (sb.shift_date + %s::time)
                        OR ta.time < (sb.shift_date + interval '1 day' + %s::time)
                END
            GROUP BY s.sequence_name
            ORDER BY s.sequence_name
        """, (
            date_from, date_to, day_of_week,
            end_time, start_time,
            start_time, end_time,
            start_time, end_time,
        ))

        return self.cursor.fetchall()

    def get_break_compliance_per_shift(self, date_from, date_to, shift_number):
        """Get break compliance for a specific shift across the week"""
        self.cursor.execute("""
            SELECT
                ab.start_time::timestamp(0) AS break_start,
                bd.break_name,
                ab.shift_number,
                ab.duration_minutes AS actual_min,
                bd.duration_minutes AS scheduled_min,
                ab.early_start_minutes,
                ab.late_end_minutes,
                CASE
                    WHEN ab.early_start_minutes > 0 AND ab.late_end_minutes > 0 THEN 'Early + Late'
                    WHEN ab.early_start_minutes > 0 THEN 'Early'
                    WHEN ab.late_end_minutes > 0 THEN 'Late'
                    ELSE 'On time'
                END AS status
            FROM actual_breaks ab
            LEFT JOIN break_definitions bd ON ab.scheduled_break_id = bd.id
            WHERE ab.start_time >= %s
                AND ab.start_time < %s::date + interval '1 day'
                AND ab.shift_number = %s
                AND ab.is_scheduled = true
            ORDER BY ab.start_time
        """, (date_from, date_to, shift_number))

        return self.cursor.fetchall()

    def get_quality_summary(self, date_from, date_to):
        """Get overall quality for the week"""
        self.cursor.execute("""
            WITH latest_per_hour AS (
                SELECT
                    shift_number,
                    hour_index,
                    MAX(good_parts) AS good_parts,
                    MAX(reject_parts) AS reject_parts,
                    MAX(rework_parts) AS rework_parts
                FROM quality_counters
                WHERE time >= %s AND time < %s::date + interval '1 day'
                GROUP BY shift_number, hour_index
            )
            SELECT
                COALESCE(SUM(good_parts), 0) AS good,
                COALESCE(SUM(reject_parts), 0) AS reject,
                COALESCE(SUM(rework_parts), 0) AS rework,
                CASE
                    WHEN SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts) > 0 THEN
                        ROUND((SUM(good_parts)::numeric /
                        (SUM(good_parts) + SUM(reject_parts) + SUM(rework_parts)) * 100), 1)
                    ELSE 100
                END AS quality_pct
            FROM latest_per_hour
        """, (date_from, date_to))

        return self.cursor.fetchone()


# =============================================================================
# CHART GENERATION
# =============================================================================
class ChartGenerator:
    """Generates matplotlib charts and saves as PNG for embedding in PDF"""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Style setup
        plt.rcParams.update({
            'font.family': 'sans-serif',
            'font.size': 22,
            'axes.titlesize': 26,
            'axes.titleweight': 'bold',
            'axes.labelsize': 22,
            'xtick.labelsize': 20,
            'ytick.labelsize': 20,
            'figure.facecolor': 'white',
        })

    def _color_by_oee(self, value):
        """Return color based on OEE value"""
        if value >= 85:
            return COLORS['oee_good']
        elif value >= 60:
            return COLORS['oee_warning']
        else:
            return COLORS['oee_bad']

    def oee_bar_chart(self, data, title, filename):
        """
        Horizontal bar chart of OEE per station.
        data: list of dicts with 'sequence_name' and 'oee'
        """
        if not data:
            return None

        names = [d['sequence_name'] for d in data]
        oee_values = [float(d['oee'] or 0) for d in data]
        colors = [self._color_by_oee(v) for v in oee_values]

        # Sort worst OEE first (top of chart)
        sorted_data = sorted(zip(names, oee_values), key=lambda x: x[1])
        names = [d[0] for d in sorted_data]
        oee_values = [d[1] for d in sorted_data]
        colors = [self._color_by_oee(v) for v in oee_values]

        fig, ax = plt.subplots(figsize=(20, max(8, len(names) * 1.1)))

        bars = ax.barh(names, oee_values, color=colors, edgecolor='white', height=0.7)

        # Add value labels at end of each bar
        for bar, val in zip(bars, oee_values):
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                    f'{val:.1f}%', va='center', ha='left', fontsize=20, fontweight='bold')

        ax.set_xlim(0, max(max(oee_values) * 1.15, 110))
        ax.set_xlabel('OEE %')
        ax.set_title(title)
        ax.axvline(x=85, color='green', linestyle='--', alpha=0.5, label='Target 85%')
        ax.legend(loc='lower right', fontsize=18)
        ax.invert_yaxis()

        plt.tight_layout()
        filepath = self.output_dir / filename
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return str(filepath)

    def downtime_stacked_bar(self, data, title, filename):
        """
        Horizontal stacked bar chart: fault/blocked/starved per station.
        data: list of dicts with 'sequence_name', 'fault_sec', 'blocked_sec', 'starved_sec'
        """
        if not data:
            return None

        names = [d['sequence_name'] for d in data]
        fault = [round(float(d['fault_sec'] or 0) / 60) for d in data]
        blocked = [round(float(d['blocked_sec'] or 0) / 60) for d in data]
        starved = [round(float(d['starved_sec'] or 0) / 60) for d in data]

        # Sort by total downtime, worst (highest) first at top
        totals = [f + b + s for f, b, s in zip(fault, blocked, starved)]
        sorted_data = sorted(zip(names, fault, blocked, starved, totals), key=lambda x: x[4])
        names = [d[0] for d in sorted_data]
        fault = [d[1] for d in sorted_data]
        blocked = [d[2] for d in sorted_data]
        starved = [d[3] for d in sorted_data]

        fig, ax = plt.subplots(figsize=(20, max(8, len(names) * 1.1)))

        ax.barh(names, fault, color=COLORS['fault'], label='Fault', height=0.7)
        ax.barh(names, blocked, left=fault, color=COLORS['blocked'], label='Blocked', height=0.7)
        left_starved = [f + b for f, b in zip(fault, blocked)]
        ax.barh(names, starved, left=left_starved, color=COLORS['starved'], label='Starved', height=0.7)

        ax.set_xlabel('Time (minutes)')
        ax.set_title(title)
        ax.legend(loc='lower right', fontsize=18)
        ax.invert_yaxis()

        plt.tight_layout()
        filepath = self.output_dir / filename
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return str(filepath)


# =============================================================================
# PDF REPORT BUILDER
# =============================================================================
class ReportBuilder:
    """Builds the PDF report using reportlab"""

    def __init__(self, output_path, report_title, date_from, date_to):
        self.output_path = output_path
        self.report_title = report_title
        self.date_from = date_from
        self.date_to = date_to
        self.story = []

        # Page setup - A4 Landscape
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=landscape(A4),
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        # Styles
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=self.styles['Title'],
            fontSize=20,
            textColor=HexColor(COLORS['header_bg']),
            spaceAfter=5,
        ))
        self.styles.add(ParagraphStyle(
            name='ShiftTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=HexColor(COLORS['header_bg']),
            spaceBefore=10,
            spaceAfter=10,
        ))
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=12,
            textColor=HexColor(COLORS['header_bg']),
            spaceBefore=8,
            spaceAfter=5,
        ))
        self.styles.add(ParagraphStyle(
            name='SmallText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=grey,
        ))

    def add_cover_page(self, quality_data):
        """First page: report title and weekly summary"""
        self.story.append(Spacer(1, 30 * mm))
        self.story.append(Paragraph(self.report_title, self.styles['ReportTitle']))
        self.story.append(Spacer(1, 5 * mm))

        date_range_str = f"{self.date_from.strftime('%A %d %B %Y')} — {self.date_to.strftime('%A %d %B %Y')}"
        self.story.append(Paragraph(date_range_str, self.styles['Heading2']))
        self.story.append(Spacer(1, 10 * mm))

        generated = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        self.story.append(Paragraph(generated, self.styles['SmallText']))
        self.story.append(Spacer(1, 15 * mm))

        # Quality summary table
        if quality_data and quality_data.get('good') is not None:
            self.story.append(Paragraph("Weekly Quality Summary", self.styles['SectionTitle']))

            q_data = [
                ['Good Parts', 'Reject Parts', 'Rework Parts', 'Total Parts', 'Quality %'],
                [
                    str(quality_data.get('good', 0) or 0),
                    str(quality_data.get('reject', 0) or 0),
                    str(quality_data.get('rework', 0) or 0),
                    str((quality_data.get('good', 0) or 0) +
                        (quality_data.get('reject', 0) or 0) +
                        (quality_data.get('rework', 0) or 0)),
                    f"{quality_data.get('quality_pct', 100)}%"
                ]
            ]

            q_table = Table(q_data, colWidths=[45 * mm] * 5)
            q_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor(COLORS['header_bg'])),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor(COLORS['row_alt'])]),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            self.story.append(q_table)

        self.story.append(PageBreak())

    def _add_chart_page(self, chart_path, title):
        """Add a single chart on its own landscape page, scaled to fill the page"""
        if not chart_path or not os.path.exists(chart_path):
            return

        self.story.append(Paragraph(title, self.styles['SectionTitle']))
        self.story.append(Spacer(1, 2 * mm))

        # Read actual image dimensions to preserve aspect ratio
        from reportlab.lib.utils import ImageReader
        img_reader = ImageReader(chart_path)
        img_w, img_h = img_reader.getSize()
        aspect = img_h / img_w

        # Available space on landscape A4: ~267mm wide x ~170mm tall (with margins)
        max_width = 267 * mm
        max_height = 170 * mm

        # Scale to fit: try full width first, check if height fits
        draw_width = max_width
        draw_height = draw_width * aspect
        if draw_height > max_height:
            draw_height = max_height
            draw_width = draw_height / aspect

        img = Image(chart_path)
        img.drawWidth = draw_width
        img.drawHeight = draw_height
        self.story.append(img)
        self.story.append(PageBreak())

    def add_shift_page(self, shift_number, day_label, oee_chart_path,
                       downtime_chart_path, oee_data, break_data):
        """Each shift gets: title page, OEE chart page, table page, downtime chart page, break table page"""

        # Shift header
        shift_title = f"Shift {shift_number} — {day_label}"
        self.story.append(Paragraph(shift_title, self.styles['ShiftTitle']))
        self.story.append(Spacer(1, 5 * mm))

        # OEE chart - full page
        if oee_chart_path and os.path.exists(oee_chart_path):
            self._add_chart_page(oee_chart_path, "OEE per Station")

        # OEE data table
        if oee_data:
            self.story.append(Paragraph("Station Detail", self.styles['SectionTitle']))
            self.story.append(Spacer(1, 3 * mm))
            table_data = [['Station', 'Availability %', 'Performance %', 'OEE %']]
            sorted_oee = sorted(oee_data, key=lambda r: float(r['oee'] or 0))
            for row in sorted_oee:
                table_data.append([
                    str(row['sequence_name']),
                    f"{row['availability']}%",
                    f"{row['performance']}%",
                    f"{row['oee']}%",
                ])

            col_widths = [60 * mm, 40 * mm, 40 * mm, 40 * mm]
            t = Table(table_data, colWidths=col_widths)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor(COLORS['header_bg'])),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -1), 0.5, grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor(COLORS['row_alt'])]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            self.story.append(t)
            self.story.append(PageBreak())

        # Downtime chart - full page
        if downtime_chart_path and os.path.exists(downtime_chart_path):
            self._add_chart_page(downtime_chart_path, "Downtime Breakdown")

        # Break compliance table
        if break_data:
            self.story.append(Paragraph("Break Compliance", self.styles['SectionTitle']))
            self.story.append(Spacer(1, 3 * mm))
            btable_data = [['Time', 'Break', 'Actual (min)', 'Scheduled (min)', 'Status']]
            for row in break_data:
                btable_data.append([
                    str(row['break_start']),
                    str(row['break_name'] or 'Unknown'),
                    str(row['actual_min'] or '-'),
                    str(row['scheduled_min'] or '-'),
                    str(row['status']),
                ])

            bt = Table(btable_data, colWidths=[50 * mm, 40 * mm, 30 * mm, 35 * mm, 30 * mm])
            bt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor(COLORS['header_bg'])),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -1), 0.5, grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor(COLORS['row_alt'])]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            self.story.append(bt)
            self.story.append(PageBreak())

    def build(self):
        """Generate the PDF"""
        self.doc.build(self.story)
        print(f"PDF generated: {self.output_path}")


# =============================================================================
# EMAIL SENDER
# =============================================================================
def send_email(pdf_path, date_from, date_to, smtp_password):
    """Send the PDF report via Gmail SMTP"""
    if not smtp_password:
        print("ERROR: No SMTP password provided.")
        print("Use --smtp-password or set REPORT_EMAIL_PASSWORD environment variable.")
        return False

    msg = MIMEMultipart()
    msg['From'] = EMAIL_CONFIG['sender']
    msg['To'] = ', '.join(EMAIL_CONFIG['recipients'])
    msg['Subject'] = (
        f"OEE Weekly Report — "
        f"{date_from.strftime('%d %b')} to {date_to.strftime('%d %b %Y')}"
    )

    body = (
        f"OEE Weekly Report\n"
        f"Period: {date_from.strftime('%A %d %B %Y')} to {date_to.strftime('%A %d %B %Y')}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Report attached as PDF."
    )
    msg.attach(MIMEText(body, 'plain'))

    # Attach PDF
    with open(pdf_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="{os.path.basename(pdf_path)}"'
        )
        msg.attach(part)

    try:
        print(f"Connecting to {EMAIL_CONFIG['smtp_server']}:{EMAIL_CONFIG['smtp_port']}...")
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['sender'], smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to: {', '.join(EMAIL_CONFIG['recipients'])}")
        return True
    except Exception as e:
        print(f"ERROR sending email: {e}")
        return False


# =============================================================================
# MAIN REPORT GENERATION
# =============================================================================
def generate_report(date_from, date_to, output_dir=None, send_email_flag=False,
                    smtp_password=None):
    """Main function: fetch data, generate charts, build PDF, optionally email"""

    if output_dir is None:
        output_dir = Path(__file__).parent / "reports"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Temp directory for chart images
    chart_dir = tempfile.mkdtemp(prefix='oee_charts_')
    chart_gen = ChartGenerator(chart_dir)

    # PDF output path
    pdf_filename = f"OEE_Report_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.pdf"
    pdf_path = str(output_dir / pdf_filename)

    # Connect to database
    db_config = load_db_config()
    print(f"Connecting to database {db_config['dbname']}@{db_config['host']}...")
    fetcher = ReportDataFetcher(db_config)

    # Initialize PDF
    report = ReportBuilder(
        pdf_path,
        "Weekly OEE Report",
        date_from,
        date_to
    )

    # Cover page with quality summary
    print("Fetching quality summary...")
    quality_data = fetcher.get_quality_summary(date_from, date_to)
    report.add_cover_page(quality_data)

    # Determine which days are in the range
    current_date = date_from
    days_in_range = []
    while current_date <= date_to:
        iso_dow = current_date.isoweekday()  # 1=Mon, 7=Sun
        if iso_dow <= 5:  # Monday to Friday only (skip weekends)
            days_in_range.append((current_date, iso_dow))
        current_date += timedelta(days=1)

    # Generate per-shift pages
    for shift_num in [1, 2, 3]:
        print(f"\nProcessing Shift {shift_num}...")

        try:
            # Aggregate across all working days for this shift
            all_oee_data = []
            all_downtime_data = []
            all_break_data = []

            for day_date, iso_dow in days_in_range:
                day_name = DAY_NAMES[iso_dow - 1]

                # Skip shifts that don't exist (e.g., no shift 3 on Saturday)
                if iso_dow >= 6:
                    continue

                print(f"  {day_name}: Fetching OEE data...")
                oee_data = fetcher.get_oee_per_station_per_shift(
                    date_from, date_to, iso_dow, shift_num
                )
                if oee_data:
                    all_oee_data = oee_data  # Use latest (they aggregate across the week)

                print(f"  {day_name}: Fetching downtime data...")
                downtime_data = fetcher.get_downtime_per_station_per_shift(
                    date_from, date_to, iso_dow, shift_num
                )
                if downtime_data:
                    all_downtime_data = downtime_data

            # Break compliance for this shift across the whole week
            print(f"  Fetching break compliance...")
            all_break_data = fetcher.get_break_compliance_per_shift(
                date_from, date_to, shift_num
            )

            # Generate charts
            oee_chart = None
            downtime_chart = None

            if all_oee_data:
                oee_chart = chart_gen.oee_bar_chart(
                    all_oee_data,
                    f"OEE per Station — Shift {shift_num}",
                    f"oee_shift{shift_num}.png"
                )

            if all_downtime_data:
                downtime_chart = chart_gen.downtime_stacked_bar(
                    all_downtime_data,
                    f"Downtime Breakdown — Shift {shift_num}",
                    f"downtime_shift{shift_num}.png"
                )

            # Determine day label
            day_label = f"{date_from.strftime('%d %b')} — {date_to.strftime('%d %b %Y')}"

            # Add shift page
            report.add_shift_page(
                shift_num, day_label,
                oee_chart, downtime_chart,
                all_oee_data, all_break_data
            )

        except Exception as e:
            print(f"  WARNING: Shift {shift_num} failed: {e}")
            print(f"  Skipping shift {shift_num}, continuing with report...")
            # Add an empty page noting the error
            report.story.append(Paragraph(
                f"Shift {shift_num} — No data available or query error",
                report.styles['ShiftTitle']
            ))
            report.story.append(Paragraph(
                f"Error: {str(e)}", report.styles['SmallText']
            ))
            report.story.append(PageBreak())

    # Build PDF
    report.build()
    fetcher.close()

    # Clean up chart temp files
    import shutil
    shutil.rmtree(chart_dir, ignore_errors=True)

    # Send email if requested
    if send_email_flag:
        send_email(pdf_path, date_from, date_to, smtp_password)

    return pdf_path


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="OEE Weekly Report Generator")
    parser.add_argument('--week-of', type=str, default=None,
                        help='Any date in the target week (YYYY-MM-DD). '
                             'Defaults to previous week.')
    parser.add_argument('--from', dest='date_from', type=str, default=None,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to', dest='date_to', type=str, default=None,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output directory (default: ./reports/)')
    parser.add_argument('--email', action='store_true',
                        help='Send report via email after generation')
    parser.add_argument('--smtp-password', type=str, default=None,
                        help='Gmail app password (or set REPORT_EMAIL_PASSWORD env var)')

    args = parser.parse_args()

    # Determine date range
    if args.date_from and args.date_to:
        date_from = date.fromisoformat(args.date_from)
        date_to = date.fromisoformat(args.date_to)
    elif args.week_of:
        ref_date = date.fromisoformat(args.week_of)
        # Get Monday of that week
        date_from = ref_date - timedelta(days=ref_date.weekday())
        date_to = date_from + timedelta(days=6)  # Sunday
    else:
        # Default: previous week (Monday to Sunday)
        today = date.today()
        last_monday = today - timedelta(days=today.weekday() + 7)
        date_from = last_monday
        date_to = last_monday + timedelta(days=6)

    print("=" * 60)
    print("OEE WEEKLY REPORT GENERATOR")
    print("=" * 60)
    print(f"Period: {date_from} to {date_to}")
    print(f"Email:  {'Yes' if args.email else 'No'}")
    print("=" * 60)

    # SMTP password
    smtp_password = args.smtp_password or os.environ.get('REPORT_EMAIL_PASSWORD', '')

    # Generate
    pdf_path = generate_report(
        date_from=date_from,
        date_to=date_to,
        output_dir=args.output,
        send_email_flag=args.email,
        smtp_password=smtp_password,
    )

    print()
    print(f"Report saved: {pdf_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
