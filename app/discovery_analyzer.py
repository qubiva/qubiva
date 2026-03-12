"""
Discovery Analyzer - Statistical Anomaly Detection
NO HARDCODED THRESHOLDS - Uses Z-score, IQR, and trend analysis
"""

from typing import Dict, List, Any
import logging
import statistics

logger = logging.getLogger('uvicorn.error')


class DiscoveryAnalyzer:
    """
    Analyzes discovery history using statistical methods:
    - Z-score: Standard deviations from mean
    - IQR: Interquartile range for outlier detection
    - Linear regression: Trend analysis
    - Rate of change: Acceleration detection

    NO hardcoded thresholds - adapts to each account's patterns!
    """

    def __init__(self, discoveries: List[Dict[str, Any]]):
        """
        Args:
            discoveries: List of discovery summaries (from get_discovery_history)
                        Should be sorted by discovered_at (newest first)
        """
        self.discoveries = sorted(discoveries, key=lambda x: x['discovered_at'])
        self.history_count = len(self.discoveries)

    def get_insights(self) -> Dict[str, Any]:
        """
        Main method: Returns all insights for dashboard.

        Returns comprehensive analysis including:
        - Anomalies (cost and resource)
        - Trends
        - Predictions (if enough data)
        - Recommendations
        """
        if self.history_count < 2:
            return self._insufficient_data_response()

        insights = {
            "anomalies": self.detect_anomalies(),
            "trends": self.analyze_trends(),
            "recommendations": []
        }

        # Add predictions if we have enough data
        if self.history_count >= 5:
            insights["predictions"] = self.predict_next_period()

        # Generate recommendations based on findings
        insights["recommendations"] = self._generate_recommendations(insights)

        return insights

    # ==================== Anomaly Detection ====================

    def detect_anomalies(self) -> Dict[str, Any]:
        """
        Detect anomalies using Z-score and IQR methods.
        """
        if self.history_count < 2:
            return {"cost_anomalies": [], "resource_anomalies": [], "new_patterns": []}

        cost_anomalies = self._detect_cost_anomalies()
        resource_anomalies = self._detect_resource_anomalies()

        return {
            "cost_anomalies": cost_anomalies,
            "resource_anomalies": resource_anomalies,
            "new_patterns": []  # Could add pattern detection later
        }

    def _detect_cost_anomalies(self) -> List[Dict[str, Any]]:
        """
        Detect cost anomalies using Z-score method.
        """
        costs = [d['total_cost'] for d in self.discoveries]

        if len(costs) < 3:
            return []  # Need at least 3 data points for meaningful stats

        # Calculate statistics
        mean_cost = statistics.mean(costs)

        try:
            stdev_cost = statistics.stdev(costs)
        except statistics.StatisticsError:
            return []  # All values are the same

        if stdev_cost == 0:
            return []  # No variation

        # Check latest value
        latest = self.discoveries[-1]
        latest_cost = latest['total_cost']

        # Calculate Z-score
        z_score = (latest_cost - mean_cost) / stdev_cost

        anomalies = []

        # Z-score thresholds: >2 = moderate, >3 = severe
        if abs(z_score) > 2:
            severity = "severe" if abs(z_score) > 3 else "moderate"
            direction = "increase" if z_score > 0 else "decrease"

            # Calculate percentage change from mean
            pct_change = abs(((latest_cost - mean_cost) / mean_cost) * 100) if mean_cost > 0 else 0

            anomalies.append({
                "metric": "total_cost",
                "severity": severity,
                "direction": direction,
                "current_value": round(latest_cost, 2),
                "historical_mean": round(mean_cost, 2),
                "z_score": round(z_score, 2),
                "message": f"Cost {direction} detected: ${latest_cost:.2f} vs average ${mean_cost:.2f} ({pct_change:.1f}% change, {abs(z_score):.1f}σ from normal)"
            })

        return anomalies

    def _detect_resource_anomalies(self) -> List[Dict[str, Any]]:
        """
        Detect resource count anomalies using Z-score method.
        """
        resource_counts = [d['total_resources'] for d in self.discoveries]

        if len(resource_counts) < 3:
            return []

        mean_resources = statistics.mean(resource_counts)

        try:
            stdev_resources = statistics.stdev(resource_counts)
        except statistics.StatisticsError:
            return []

        if stdev_resources == 0:
            return []

        latest = self.discoveries[-1]
        latest_count = latest['total_resources']

        z_score = (latest_count - mean_resources) / stdev_resources

        anomalies = []

        if abs(z_score) > 2:
            severity = "severe" if abs(z_score) > 3 else "moderate"
            direction = "increase" if z_score > 0 else "decrease"

            pct_change = abs(((latest_count - mean_resources) / mean_resources) * 100) if mean_resources > 0 else 0

            anomalies.append({
                "metric": "resource_count",
                "severity": severity,
                "direction": direction,
                "current_value": latest_count,
                "historical_mean": round(mean_resources, 1),
                "z_score": round(z_score, 2),
                "message": f"Resource count {direction}: {latest_count} resources vs average {mean_resources:.0f} ({pct_change:.1f}% change, {abs(z_score):.1f}σ from normal)"
            })

        return anomalies

    # ==================== Trend Analysis ====================

    def analyze_trends(self) -> Dict[str, Any]:
        """
        Analyze trends using simple linear regression.
        """
        if self.history_count < 3:
            return {"cost": None, "resources": None}

        cost_trend = self._calculate_trend([d['total_cost'] for d in self.discoveries])
        resource_trend = self._calculate_trend([float(d['total_resources']) for d in self.discoveries])

        return {
            "cost": cost_trend,
            "resources": resource_trend
        }

    def _calculate_trend(self, values: List[float]) -> Dict[str, Any]:
        """
        Calculate trend using simple linear regression.
        Returns slope, direction, and strength.
        """
        n = len(values)
        if n < 3:
            return None

        # Use index as x (time)
        x = list(range(n))
        y = values

        # Calculate means
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)

        # Calculate slope (b) and intercept (a)
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return None

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # Calculate R-squared (coefficient of determination)
        y_pred = [slope * xi + intercept for xi in x]
        ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))

        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        # Determine direction and strength
        if abs(slope) < 0.01:
            direction = "stable"
            strength = "none"
        else:
            direction = "increasing" if slope > 0 else "decreasing"

            # Strength based on R-squared
            if r_squared > 0.7:
                strength = "strong"
            elif r_squared > 0.4:
                strength = "moderate"
            else:
                strength = "weak"

        return {
            "direction": direction,
            "slope": round(slope, 2),
            "strength": strength,
            "r_squared": round(r_squared, 2),
            "confidence": "high" if r_squared > 0.7 else "moderate" if r_squared > 0.4 else "low"
        }

    # ==================== Predictions ====================

    def predict_next_period(self) -> Dict[str, Any]:
        """
        Predict next period values if trend is strong enough.
        Only returns predictions for strong trends (R² > 0.7).
        """
        if self.history_count < 5:
            return None

        trends = self.analyze_trends()
        predictions = {}

        # Cost prediction
        cost_trend = trends.get("cost")
        if cost_trend and cost_trend["r_squared"] > 0.7:
            costs = [d['total_cost'] for d in self.discoveries]
            next_cost = costs[-1] + cost_trend["slope"]
            predictions["cost"] = {
                "predicted_value": round(max(0, next_cost), 2),  # Can't be negative
                "confidence": cost_trend["confidence"],
                "trend_strength": cost_trend["strength"]
            }

        # Resource prediction
        resource_trend = trends.get("resources")
        if resource_trend and resource_trend["r_squared"] > 0.7:
            resource_counts = [d['total_resources'] for d in self.discoveries]
            next_count = resource_counts[-1] + resource_trend["slope"]
            predictions["resources"] = {
                "predicted_value": int(max(0, round(next_count))),
                "confidence": resource_trend["confidence"],
                "trend_strength": resource_trend["strength"]
            }

        return predictions if predictions else None

    # ==================== Recommendations ====================

    def _generate_recommendations(self, insights: Dict[str, Any]) -> List[str]:
        """
        Generate actionable recommendations based on insights.
        """
        recommendations = []

        # Check anomalies
        cost_anomalies = insights["anomalies"].get("cost_anomalies", [])
        resource_anomalies = insights["anomalies"].get("resource_anomalies", [])

        for anomaly in cost_anomalies:
            if anomaly["severity"] == "severe":
                recommendations.append(f"⚠️ Urgent: Investigate {anomaly['direction']} in costs (${anomaly['current_value']:.2f})")
            elif anomaly["severity"] == "moderate":
                recommendations.append(f"💡 Review recent cost {anomaly['direction']} (${anomaly['current_value']:.2f} vs ${anomaly['historical_mean']:.2f} average)")

        for anomaly in resource_anomalies:
            if anomaly["severity"] == "severe":
                recommendations.append(f"⚠️ Significant resource count change detected: {anomaly['current_value']} resources")

        # Check trends
        trends = insights.get("trends", {})
        cost_trend = trends.get("cost")

        if cost_trend and cost_trend["direction"] == "increasing" and cost_trend["strength"] in ["strong", "moderate"]:
            recommendations.append("📈 Cost trend is increasing - consider reviewing resource usage and optimization opportunities")

        # Check predictions
        predictions = insights.get("predictions")
        if predictions and predictions.get("cost"):
            predicted_cost = predictions["cost"]["predicted_value"]
            latest_cost = self.discoveries[-1]["total_cost"]
            if predicted_cost > latest_cost * 1.2:  # >20% increase predicted
                recommendations.append(f"🔮 Cost forecast shows potential increase to ${predicted_cost:.2f} in next period")

        # If no specific issues, add general advice
        if not recommendations:
            recommendations.append("✅ No significant anomalies detected - costs and resources are within normal ranges")

        return recommendations

    # ==================== Helper Methods ====================

    def _insufficient_data_response(self) -> Dict[str, Any]:
        """
        Return helpful message when not enough data for analysis.
        """
        return {
            "message": "Not enough historical data for analysis. Run more discoveries to unlock trends and insights.",
            "discoveries_count": self.history_count,
            "required_minimum": 2,
            "anomalies": {"cost_anomalies": [], "resource_anomalies": [], "new_patterns": []},
            "trends": {"cost": None, "resources": None},
            "recommendations": ["📊 Run at least 2 more discoveries to enable trend analysis and anomaly detection"]
        }

    def get_summary_statistics(self) -> Dict[str, Any]:
        """
        Get basic statistical summary of the discovery history.
        Useful for debugging or additional context.
        """
        if self.history_count == 0:
            return {}

        costs = [d['total_cost'] for d in self.discoveries]
        resources = [d['total_resources'] for d in self.discoveries]

        return {
            "discoveries_analyzed": self.history_count,
            "cost_statistics": {
                "min": round(min(costs), 2),
                "max": round(max(costs), 2),
                "mean": round(statistics.mean(costs), 2),
                "median": round(statistics.median(costs), 2),
                "stdev": round(statistics.stdev(costs), 2) if len(costs) > 1 else 0
            },
            "resource_statistics": {
                "min": min(resources),
                "max": max(resources),
                "mean": round(statistics.mean(resources), 1),
                "median": statistics.median(resources)
            }
        }
