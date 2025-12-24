"""Weather API node.

Fetches weather data from OpenWeatherMap API.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from src.models.node import (
    NodeCategory,
    NodeDefinition,
    NodeInput,
    NodeInputType,
    NodeOutput,
    NodeOutputType,
)
from src.nodes.base import BaseNode, NodeContext, NodeExecutionError, NodeValidationError


@dataclass
class WeatherInput:
    """Input for weather node."""

    location: str
    units: str = "metric"


@dataclass
class WeatherOutput:
    """Output from weather node."""

    location: str
    country: str
    temperature: float
    feels_like: float
    humidity: int
    description: str
    wind_speed: float
    raw_data: dict[str, Any]


class WeatherNode(BaseNode[WeatherInput, WeatherOutput]):
    """Weather API node for fetching weather data.

    Requires 'weather_api_key' credential (OpenWeatherMap API key).

    Example:
        result = await node.run(
            {"location": "London"},
            context
        )
    """

    def get_definition(self) -> NodeDefinition:
        """Get node definition."""
        return NodeDefinition(
            name="weather_api",
            display_name="Weather API",
            description="Get current weather data for a location",
            category=NodeCategory.API,
            credential_type="weather_api_key",
            inputs=[
                NodeInput(
                    name="location",
                    display_name="Location",
                    type=NodeInputType.STRING,
                    description="City name (e.g., 'London' or 'London,UK')",
                    required=True,
                ),
                NodeInput(
                    name="units",
                    display_name="Units",
                    type=NodeInputType.STRING,
                    description="Temperature units",
                    required=False,
                    default="metric",
                    options=["metric", "imperial", "kelvin"],
                ),
            ],
            outputs=[
                NodeOutput(
                    name="location",
                    display_name="Location",
                    type=NodeOutputType.STRING,
                    description="City name",
                ),
                NodeOutput(
                    name="temperature",
                    display_name="Temperature",
                    type=NodeOutputType.NUMBER,
                    description="Current temperature",
                ),
                NodeOutput(
                    name="description",
                    display_name="Description",
                    type=NodeOutputType.STRING,
                    description="Weather description",
                ),
                NodeOutput(
                    name="raw_data",
                    display_name="Raw Data",
                    type=NodeOutputType.JSON,
                    description="Full API response",
                ),
            ],
            tags=["weather", "api", "data"],
        )

    def validate_input(self, input_data: dict[str, Any]) -> WeatherInput:
        """Validate input data."""
        location = input_data.get("location")

        if not location:
            raise NodeValidationError("Location is required", field="location")

        if not isinstance(location, str):
            raise NodeValidationError("Location must be a string", field="location")

        units = input_data.get("units", "metric")
        if units not in ["metric", "imperial", "kelvin"]:
            raise NodeValidationError(
                f"Invalid units: {units}. Must be metric, imperial, or kelvin",
                field="units",
            )

        return WeatherInput(location=location, units=units)

    async def execute(
        self,
        input_data: WeatherInput,
        context: NodeContext,
    ) -> WeatherOutput:
        """Execute weather API call."""
        api_key = context.credentials.get("api_key")
        if not api_key:
            raise NodeExecutionError(
                message="Weather API key not found in credentials",
                node_name="weather_api",
                error_code="MISSING_CREDENTIAL",
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "q": input_data.location,
                        "appid": api_key,
                        "units": input_data.units,
                    },
                    timeout=10.0,
                )

                if response.status_code == 404:
                    raise NodeExecutionError(
                        message=f"Location not found: {input_data.location}",
                        node_name="weather_api",
                        error_code="NOT_FOUND",
                    )

                response.raise_for_status()
                data = response.json()

                return WeatherOutput(
                    location=data["name"],
                    country=data["sys"]["country"],
                    temperature=data["main"]["temp"],
                    feels_like=data["main"]["feels_like"],
                    humidity=data["main"]["humidity"],
                    description=data["weather"][0]["description"],
                    wind_speed=data["wind"]["speed"],
                    raw_data=data,
                )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise NodeExecutionError(
                    message="Invalid weather API key",
                    node_name="weather_api",
                    error_code="AUTH_ERROR",
                ) from e
            raise NodeExecutionError(
                message=f"Weather API error: {e.response.text}",
                node_name="weather_api",
                error_code="API_ERROR",
            ) from e
        except httpx.RequestError as e:
            raise NodeExecutionError(
                message=f"Request failed: {str(e)}",
                node_name="weather_api",
                error_code="NETWORK_ERROR",
            ) from e
