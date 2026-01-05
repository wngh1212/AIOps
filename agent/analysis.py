import json
import logging
import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


class DateRangeExtractor:
    """Extract date ranges from natural language (English)"""

    @staticmethod
    def extract_date_range(text):
        now = datetime.now()
        text_lower = text.lower()

        month_names = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }

        month_pattern = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)(?:\s*(?:to|through|until|-|~)\s*)(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
        month_match = re.search(month_pattern, text_lower)

        if month_match:
            start_month = month_names[month_match.group(1)]
            end_month = month_names[month_match.group(2)]
            year = now.year

            # If end month < current month, assume previous year
            if end_month < now.month:
                year = now.year - 1

            start_date = datetime(year, start_month, 1)
            # Get last day of end month
            next_month = datetime(year, end_month, 1) + relativedelta(months=1)
            end_date = next_month - timedelta(days=1)

            period_label = f"{month_match.group(1).capitalize()} to {month_match.group(2).capitalize()}"
            logger.debug(f"Extracted month range: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        # Relative period: "last 3 months", "past 6 months"
        relative_pattern = r"(last|past|previous)\s+(\d+)\s+months?"
        relative_match = re.search(relative_pattern, text_lower)

        if relative_match:
            months = int(relative_match.group(2))
            end_date = now
            start_date = now - relativedelta(months=months)

            period_label = f"Last {months} months"
            logger.debug(f"Extracted relative range: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        # Quarter "Q1", "2nd quarter"
        quarter_pattern = r"(?:q|quarter)\s*([1-4])|([1-4])(?:st|nd|rd|th)\s+quarter"
        quarter_match = re.search(quarter_pattern, text_lower)

        if quarter_match:
            quarter = int(quarter_match.group(1) or quarter_match.group(2))
            year = now.year

            start_month = (quarter - 1) * 3 + 1
            end_month = quarter * 3

            start_date = datetime(year, start_month, 1)
            next_month = datetime(year, end_month, 1) + relativedelta(months=1)
            end_date = next_month - timedelta(days=1)

            period_label = f"Q{quarter} {year}"
            logger.debug(f"Extracted quarter: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        if any(w in text_lower for w in ["last year", "previous year"]):
            year = now.year - 1
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31)
            period_label = f"{year}"
            logger.debug(f"Extracted last year: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        if any(w in text_lower for w in ["this year", "current year"]):
            year = now.year
            start_date = datetime(year, 1, 1)
            end_date = now
            period_label = f"{year} (so far)"
            logger.debug(f"Extracted this year: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        # Specific year: "2025", "2024"
        year_pattern = r"(20\d{2})\s*(?:year)?"
        year_match = re.search(year_pattern, text)
        if year_match:
            year = int(year_match.group(1))
            start_date = datetime(year, 1, 1)
            # If past year, full year. If current year, until today
            if year < now.year:
                end_date = datetime(year, 12, 31)
            else:
                end_date = now
            period_label = f"{year}"
            logger.debug(f"Extracted year: {start_date} ~ {end_date}")
            return start_date, end_date, period_label

        start_date = now.replace(day=1)
        end_date = now
        period_label = "This month"
        logger.debug("Using default range (this month)")
        return start_date, end_date, period_label

    @staticmethod
    def format_date_range(start_date, end_date):
        """Convert date range to AWS API format (YYYY-MM-DD)"""
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


class AnalysisAgent:
    def __init__(self, mcp_server, llm):
        self.server = mcp_server
        self.llm = llm
        self.date_extractor = DateRangeExtractor()

    def analyze_cost_trend(self, user_query=None):
        try:
            #  Extract date range from natural language
            if user_query:
                start_date, end_date, period_label = (
                    self.date_extractor.extract_date_range(user_query)
                )
            else:
                # Default: This month
                now = datetime.now()
                start_date = now.replace(day=1)
                end_date = now
                period_label = "This month"

            logger.info(f"Analyzing cost for period: {start_date} ~ {end_date}")

            # Fetch cost data from AWS for specified range
            start_str, end_str = self.date_extractor.format_date_range(
                start_date, end_date
            )

            cost_result = self.server.get_cost_by_date(start_str, end_str)

            current_cost = self._extract_cost(cost_result)

            # Step 3: Fetch previous period data for comparison
            period_duration = (end_date - start_date).days
            prev_end = start_date - timedelta(days=1)
            prev_start = prev_end - timedelta(days=period_duration)

            prev_start_str, prev_end_str = self.date_extractor.format_date_range(
                prev_start, prev_end
            )

            prev_cost_result = self.server.get_cost_by_date(
                prev_start_str, prev_end_str
            )

            prev_cost = self._extract_cost(prev_cost_result)

            # LLM analysis
            diff = current_cost - prev_cost
            percent = (diff / prev_cost * 100) if prev_cost > 0 else 0

            analysis_prompt = f"""
[ROLE] AWS Cost Analyst

[PERIOD] {period_label}
Date Range: {start_str} to {end_str}

[COST DATA]
Current period: ${current_cost:.2f}
Previous comparable period: ${prev_cost:.2f}
Difference: ${diff:.2f} ({percent:+.1f}%)

[TASK]
1. Analyze cost trend (increase/decrease and reasons)
2. Identify main cost drivers
3. Provide optimization recommendations
4. Forecast future trend

[OUTPUT] Clear, actionable analysis with specific insights"""

            analysis = self.llm.invoke(analysis_prompt)

            output = f"""
Cost Analysis Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Period: {period_label} ({start_str} to {end_str})

Cost Overview:
Current period: ${current_cost:.2f}
Previous comparable period: ${prev_cost:.2f}
Change: ${diff:.2f}
Change rate: {percent:+.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI Analysis & Recommendations:
{analysis}
"""
            logger.info("Cost analysis completed")
            return output

        except Exception as e:
            logger.error(f"Cost analysis failed: {e}", exc_info=True)
            return f"Error during cost analysis: {str(e)}"

    def analyze_resource_usage(self):
        """Analyze resource utilization (existing code)"""
        try:
            logger.info("Analyzing resource usage")

            instances_result = self.server.call_tool(
                "list_instances", {"status": "all"}
            )

            instance_metrics = []
            for line in instances_result.split("\n"):
                if "ID:" in line:
                    parts = self._parse_instance_line(line)
                    if parts:
                        instance_metrics.append(parts)

            if not instance_metrics:
                return "No active instances found."

            data_str = json.dumps(instance_metrics, indent=2, ensure_ascii=False)
            analysis_prompt = f"""
[ROLE] AWS Resource Optimization Expert

[DATA]
Instance resource utilization:
{data_str}

[TASK]
1. Identify top 3 resource-consuming instances
2. Analyze instances with high CPU usage and root causes
3. Identify underutilized/idle instances
4. Provide specific optimization recommendations

[OUTPUT] Actionable optimization strategy with priorities"""

            analysis = self.llm.invoke(analysis_prompt)

            output = f"""
Resource Utilization Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Instance Status:
{instances_result}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI Optimization Analysis:
{analysis}
"""
            logger.info("Resource analysis completed")
            return output

        except Exception as e:
            logger.error(f"Resource analysis failed: {e}", exc_info=True)
            return f"Error during resource analysis: {str(e)}"

    def analyze_high_cpu_instances(self, threshold=80.0):
        """Analyze high CPU utilization instances (existing code)"""
        try:
            logger.info(f"Analyzing instances with CPU > {threshold}%")

            instances_result = self.server.call_tool(
                "list_instances", {"status": "all"}
            )

            high_cpu_instances = []
            for line in instances_result.split("\n"):
                if "ID:" in line:
                    parts = self._parse_instance_line(line)
                    if parts and parts.get("cpu", 0) > threshold:
                        high_cpu_instances.append(parts)

            if not high_cpu_instances:
                return f"No instances exceeding {threshold}% CPU utilization."

            data_str = json.dumps(high_cpu_instances, indent=2, ensure_ascii=False)
            analysis_prompt = f"""
[ROLE] AWS Performance Engineer

[ALERT] High CPU Utilization Detected
Threshold: {threshold}%

[DATA]
{data_str}

[TASK]
1. Analyze root causes for each high-CPU instance
2. Recommend immediate actions (restart, scale-up, etc.)
3. Suggest long-term solutions
4. Provide monitoring recommendations

[OUTPUT] Priority-ordered action items with clear instructions"""

            analysis = self.llm.invoke(analysis_prompt)

            output = f"""
High CPU Utilization Instances Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Threshold: {threshold}%

Affected Instances:
{data_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI Recommendations:
{analysis}
"""
            logger.info("High CPU analysis completed")
            return output

        except Exception as e:
            logger.error(f"High CPU analysis failed: {e}", exc_info=True)
            return f"Error during CPU analysis: {str(e)}"

    def _extract_cost(self, result):
        """Extract cost value from result"""
        try:
            match = re.search(r"\$(\d+\.?\d*)", str(result))
            return float(match.group(1)) if match else 0.0
        except:
            return 0.0

    def _parse_instance_line(self, line):
        """Parse instance information line"""
        try:
            parts = {}

            id_match = re.search(r"ID: (i-[\w]+)", line)
            name_match = re.search(r"Name: ([\w\-\s]+) \|", line)
            state_match = re.search(r"State: (\w+)", line)
            cpu_match = re.search(r"CPU: ([\d\.]+)%", line)

            if id_match:
                parts["instance_id"] = id_match.group(1)
            if name_match:
                parts["name"] = name_match.group(1).strip()
            if state_match:
                parts["state"] = state_match.group(1)
            if cpu_match:
                parts["cpu"] = float(cpu_match.group(1))

            return parts if parts else None
        except:
            return None
