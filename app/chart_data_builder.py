"""
Chart Data Builder - Formats discovery data for Chart.js
Generates chart-ready JSON for AdminLTE dashboard
"""

from typing import Dict, List, Any
import logging

logger = logging.getLogger('uvicorn.error')


class ChartDataBuilder:
    """
    Builds Chart.js compatible data structures from discovery data.

    Supported chart types:
    - Pie: Cost by service
    - Donut: Resources by type
    - Bar: Resources by region
    - Line: Cost/resource trends over time
    """

    # AdminLTE color palette
    COLORS = {
        'primary': '#3c8dbc',
        'success': '#00a65a',
        'info': '#00c0ef',
        'warning': '#f39c12',
        'danger': '#f56954',
        'purple': '#605ca8',
        'teal': '#39cccc',
        'orange': '#ff851b',
        'gray': '#d2d6de'
    }

    COLOR_PALETTE = [
        '#f56954',  # Red
        '#00a65a',  # Green
        '#f39c12',  # Orange
        '#00c0ef',  # Light blue
        '#3c8dbc',  # Blue
        '#d2d6de',  # Gray
        '#605ca8',  # Purple
        '#39cccc',  # Teal
        '#ff851b',  # Dark orange
    ]

    def __init__(self, discovery_data: Dict[str, Any]):
        """
        Args:
            discovery_data: Enhanced discovery data from DiscoveryManagerEnhanced
        """
        self.data = discovery_data
        self.summary = discovery_data.get('summary', {})

    def build_all_charts(self) -> Dict[str, Any]:
        """
        Build all charts at once for dashboard.

        Returns dict with all chart configurations.
        """
        return {
            "cost_pie": self.build_cost_pie_chart(),
            "resource_donut": self.build_resource_donut_chart(),
            "region_bar": self.build_region_bar_chart(),
            "service_cost_bar": self.build_service_cost_bar_chart()
        }

    def build_cost_pie_chart(self) -> Dict[str, Any]:
        """
        Pie chart: Cost breakdown by service.
        """
        cost_by_service = self.summary.get('by_service_cost', {})

        if not cost_by_service:
            return self._empty_chart()

        # Sort by cost (descending) and take top 10
        sorted_services = sorted(
            cost_by_service.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        # Group small services into "Other"
        if len(cost_by_service) > 10:
            other_cost = sum(cost for service, cost in sorted(
                cost_by_service.items(),
                key=lambda x: x[1],
                reverse=True
            )[10:])
            sorted_services.append(("Other", other_cost))

        labels = [self._shorten_service_name(service) for service, _ in sorted_services]
        data = [cost for _, cost in sorted_services]

        return {
            "labels": labels,
            "datasets": [{
                "data": data,
                "backgroundColor": self.COLOR_PALETTE[:len(labels)]
            }]
        }

    def build_resource_donut_chart(self) -> Dict[str, Any]:
        """
        Donut chart: Resource count by type.
        """
        resource_by_type = self.summary.get('by_type', {})

        if not resource_by_type:
            return self._empty_chart()

        # Sort by count (descending) and take top 10
        sorted_types = sorted(
            resource_by_type.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        # Group small types into "Other"
        if len(resource_by_type) > 10:
            other_count = sum(count for rtype, count in sorted(
                resource_by_type.items(),
                key=lambda x: x[1],
                reverse=True
            )[10:])
            sorted_types.append(("Other", other_count))

        labels = [self._format_resource_type(rtype) for rtype, _ in sorted_types]
        data = [count for _, count in sorted_types]

        return {
            "labels": labels,
            "datasets": [{
                "data": data,
                "backgroundColor": self.COLOR_PALETTE[:len(labels)]
            }]
        }

    def build_region_bar_chart(self) -> Dict[str, Any]:
        """
        Bar chart: Resources by region/location.
        """
        resource_by_region = self.summary.get('by_region', {})

        if not resource_by_region:
            return self._empty_chart()

        # Sort by count (descending)
        sorted_regions = sorted(
            resource_by_region.items(),
            key=lambda x: x[1],
            reverse=True
        )

        labels = [region for region, _ in sorted_regions]
        data = [count for _, count in sorted_regions]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Resources",
                "data": data,
                "backgroundColor": self.COLORS['primary']
            }]
        }

    def build_service_cost_bar_chart(self) -> Dict[str, Any]:
        """
        Horizontal bar chart: Top services by cost.
        Better for comparing service costs than pie chart.
        """
        cost_by_service = self.summary.get('by_service_cost', {})

        if not cost_by_service:
            return self._empty_chart()

        # Sort by cost (descending) and take top 10
        sorted_services = sorted(
            cost_by_service.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        labels = [self._shorten_service_name(service) for service, _ in sorted_services]
        data = [cost for _, cost in sorted_services]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Cost ($)",
                "data": data,
                "backgroundColor": self.COLORS['success']
            }]
        }

    def build_cost_trend_line_chart(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Line chart: Cost trend over time.
        Requires historical data.

        Args:
            history: List of discovery summaries from get_discovery_history
        """
        if not history or len(history) < 2:
            return self._empty_chart()

        # Sort by date
        sorted_history = sorted(history, key=lambda x: x['discovered_at'])

        labels = [self._format_date(d['discovered_at']) for d in sorted_history]
        costs = [d['total_cost'] for d in sorted_history]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Cost ($)",
                "data": costs,
                "borderColor": self.COLORS['primary'],
                "backgroundColor": 'rgba(60, 141, 188, 0.1)',
                "fill": True,
                "tension": 0.4  # Smooth line
            }]
        }

    def build_resource_trend_line_chart(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Line chart: Resource count trend over time.
        Requires historical data.
        """
        if not history or len(history) < 2:
            return self._empty_chart()

        sorted_history = sorted(history, key=lambda x: x['discovered_at'])

        labels = [self._format_date(d['discovered_at']) for d in sorted_history]
        resources = [d['total_resources'] for d in sorted_history]

        return {
            "labels": labels,
            "datasets": [{
                "label": "Resources",
                "data": resources,
                "borderColor": self.COLORS['success'],
                "backgroundColor": 'rgba(0, 166, 90, 0.1)',
                "fill": True,
                "tension": 0.4
            }]
        }

    def build_combined_trend_chart(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Dual-axis line chart: Both cost and resources over time.
        """
        if not history or len(history) < 2:
            return self._empty_chart()

        sorted_history = sorted(history, key=lambda x: x['discovered_at'])

        labels = [self._format_date(d['discovered_at']) for d in sorted_history]
        costs = [d['total_cost'] for d in sorted_history]
        resources = [d['total_resources'] for d in sorted_history]

        return {
            "labels": labels,
            "datasets": [
                {
                    "label": "Cost ($)",
                    "data": costs,
                    "borderColor": self.COLORS['primary'],
                    "backgroundColor": 'rgba(60, 141, 188, 0.1)',
                    "yAxisID": 'y-cost',
                    "fill": True,
                    "tension": 0.4
                },
                {
                    "label": "Resources",
                    "data": resources,
                    "borderColor": self.COLORS['success'],
                    "backgroundColor": 'rgba(0, 166, 90, 0.1)',
                    "yAxisID": 'y-resources',
                    "fill": True,
                    "tension": 0.4
                }
            ],
            "scales": {
                "y-cost": {
                    "type": "linear",
                    "position": "left",
                    "title": {
                        "display": True,
                        "text": "Cost ($)"
                    }
                },
                "y-resources": {
                    "type": "linear",
                    "position": "right",
                    "title": {
                        "display": True,
                        "text": "Resource Count"
                    },
                    "grid": {
                        "drawOnChartArea": False
                    }
                }
            }
        }

    # ==================== Helper Methods ====================

    def _empty_chart(self) -> Dict[str, Any]:
        """Return empty chart structure."""
        return {
            "labels": [],
            "datasets": [{
                "data": [],
                "backgroundColor": []
            }]
        }

    def _shorten_service_name(self, service_name: str) -> str:
        """
        Shorten long AWS service names for better chart display.
        """
        replacements = {
            'Amazon ': '',
            'AWS ': '',
            'Elastic Compute Cloud': 'EC2',
            'Simple Storage Service': 'S3',
            'Relational Database Service': 'RDS',
            'Elastic Container Service': 'ECS',
            'Elastic Kubernetes Service': 'EKS',
            'Virtual Private Cloud': 'VPC',
            'Key Management Service': 'KMS',
            'CloudFront': 'CloudFront',
            'Route 53': 'Route53',
            ' - Other': ''
        }

        shortened = service_name
        for old, new in replacements.items():
            shortened = shortened.replace(old, new)

        # Truncate if still too long
        if len(shortened) > 30:
            shortened = shortened[:27] + '...'

        return shortened

    def _format_resource_type(self, resource_type: str) -> str:
        """
        Format resource type for display.
        Example: aws_s3_bucket -> S3 Bucket
        """
        # Remove provider prefix
        parts = resource_type.split('_')
        if len(parts) > 1:
            parts = parts[1:]  # Remove 'aws', 'gcp', 'azure'

        # Capitalize and join
        formatted = ' '.join(word.capitalize() for word in parts)

        # Handle special cases
        replacements = {
            'S3': 'S3',
            'Ec2': 'EC2',
            'Rds': 'RDS',
            'Ecs': 'ECS',
            'Eks': 'EKS',
            'Vpc': 'VPC',
            'Iam': 'IAM',
            'Kms': 'KMS',
            'Db': 'DB'
        }

        for old, new in replacements.items():
            formatted = formatted.replace(old, new)

        return formatted

    def _format_date(self, iso_date: str) -> str:
        """
        Format ISO date string for chart labels.
        Example: 2025-10-24T17:12:32Z -> Oct 24
        """
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
            return dt.strftime('%b %d')
        except Exception as e:
            logger.warning(f"Failed to format date {iso_date}: {e}")
            return iso_date[:10]  # Return just date part

    def build_tagging_compliance_chart(self) -> Dict[str, Any]:
        """
        Donut chart: Tagging compliance (tagged vs untagged).
        """
        tagging = self.summary.get('tagging', {})

        if not tagging or tagging.get('total', 0) == 0:
            return self._empty_chart()

        tagged = tagging.get('tagged', 0)
        untagged = tagging.get('untagged', 0)

        return {
            "labels": ["Tagged", "Untagged"],
            "datasets": [{
                "data": [tagged, untagged],
                "backgroundColor": [self.COLORS['success'], self.COLORS['danger']]
            }]
        }
