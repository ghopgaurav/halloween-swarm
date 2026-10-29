import json

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from halloween_swarm.config import BRAIN_MODEL, FAST_MODEL, doctrine, parasail_llm
from halloween_swarm.schemas import CivilianReport, IntelReport, ReviewVerdict, SensorReport, TickDecision
from halloween_swarm.tools import CivilianRegistryTool, GroundSightingTool, SensorPatternTool

# Specialists in the order they are kept when the tick's agent budget is tight; the commander always runs.
SPECIALISTS = ["civilian_officer", "sensor_analyst", "intel_analyst"]
TASK_OF = {"civilian_officer": "civilian_task", "sensor_analyst": "sensor_task", "intel_analyst": "intel_task"}


@CrewBase
class HalloweenSwarm():
    """The contested part of one tick: only the specialists triage asked for, then the commander.

    Evidence (embedding matches, You.com results) is fetched in code and put in each prompt, and every
    agent answers with schema-constrained JSON, so each agent costs exactly one LLM call.
    """

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self, needed: list[str], max_active_agents: int) -> None:
        wanted = [s for s in SPECIALISTS if s in needed]
        self.roster = wanted[: max(0, max_active_agents - 1)]

    @agent
    def sensor_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['sensor_analyst'], # type: ignore[index]
            llm=parasail_llm(FAST_MODEL, response_format=SensorReport),
            max_iter=1,
        )

    @agent
    def intel_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['intel_analyst'], # type: ignore[index]
            llm=parasail_llm(FAST_MODEL, response_format=IntelReport),
            max_iter=1,
        )

    @agent
    def civilian_officer(self) -> Agent:
        return Agent(
            config=self.agents_config['civilian_officer'], # type: ignore[index]
            llm=parasail_llm(FAST_MODEL, response_format=CivilianReport),
            max_iter=1,
        )

    @agent
    def commander(self) -> Agent:
        return Agent(
            config=self.agents_config['commander'], # type: ignore[index]
            # glm-53 reasons at length by default (25k tokens on one sector); low effort decides in ~1s.
            llm=parasail_llm(BRAIN_MODEL, response_format=TickDecision, reasoning_effort="low"),
            max_iter=1,
        )

    @task
    def sensor_task(self) -> Task:
        return Task(
            config=self.tasks_config['sensor_task'], # type: ignore[index]
            output_pydantic=SensorReport,
            async_execution=True,
        )

    @task
    def intel_task(self) -> Task:
        return Task(
            config=self.tasks_config['intel_task'], # type: ignore[index]
            output_pydantic=IntelReport,
            async_execution=True,
        )

    @task
    def civilian_task(self) -> Task:
        return Task(
            config=self.tasks_config['civilian_task'], # type: ignore[index]
            output_pydantic=CivilianReport,
            async_execution=True,
        )

    @task
    def command_task(self) -> Task:
        return Task(
            config=self.tasks_config['command_task'], # type: ignore[index]
            output_pydantic=TickDecision,
        )

    @crew
    def crew(self) -> Crew:
        """The roster fits the tick's max_active_agents; the commander sees only the specialists' reports."""
        specialist_tasks = [t for t in self.tasks if t.name in {TASK_OF[n] for n in self.roster}]
        command = next(t for t in self.tasks if t.name == "command_task")
        command.context = specialist_tasks
        return Crew(
            agents=[t.agent for t in [*specialist_tasks, command]],
            tasks=[*specialist_tasks, command],
            process=Process.sequential,
            verbose=False,
        )


@CrewBase
class ReviewSwarm():
    """After an escalation is submitted: the full swarm, each specialist with its own tool and slice, reviews the
    decision and writes the dispatch. Runs in the background, off the scoring path."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/review_tasks.yaml"
    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self, report: dict, max_agents: int) -> None:
        self.report = report
        # Commander plus as many specialists as fit (civilian officer first, then sensor, then intel).
        self.roster = SPECIALISTS[: max(0, min(len(SPECIALISTS), max_agents - 1))]

    @agent
    def sensor_analyst(self) -> Agent:
        return Agent(config=self.agents_config['sensor_analyst'], # type: ignore[index]
                     llm=parasail_llm(FAST_MODEL), tools=[SensorPatternTool([self.report])], max_iter=3)

    @agent
    def intel_analyst(self) -> Agent:
        return Agent(config=self.agents_config['intel_analyst'], # type: ignore[index]
                     llm=parasail_llm(FAST_MODEL), tools=[GroundSightingTool()], max_iter=3)

    @agent
    def civilian_officer(self) -> Agent:
        return Agent(config=self.agents_config['civilian_officer'], # type: ignore[index]
                     llm=parasail_llm(FAST_MODEL), tools=[CivilianRegistryTool([self.report])], max_iter=3)

    @agent
    def commander(self) -> Agent:
        return Agent(config=self.agents_config['commander'], # type: ignore[index]
                     llm=parasail_llm(BRAIN_MODEL, response_format=ReviewVerdict, reasoning_effort="low"), max_iter=1)

    @task
    def review_sensor_task(self) -> Task:
        return Task(config=self.tasks_config['review_sensor_task'], output_pydantic=SensorReport, async_execution=True) # type: ignore[index]

    @task
    def review_intel_task(self) -> Task:
        return Task(config=self.tasks_config['review_intel_task'], output_pydantic=IntelReport, async_execution=True) # type: ignore[index]

    @task
    def review_civilian_task(self) -> Task:
        return Task(config=self.tasks_config['review_civilian_task'], output_pydantic=CivilianReport, async_execution=True) # type: ignore[index]

    @task
    def review_command_task(self) -> Task:
        return Task(config=self.tasks_config['review_command_task'], output_pydantic=ReviewVerdict) # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        wanted = {"review_" + TASK_OF[n] for n in self.roster}
        specialist_tasks = [t for t in self.tasks if t.name in wanted]
        command = next(t for t in self.tasks if t.name == "review_command_task")
        command.context = specialist_tasks
        return Crew(agents=[t.agent for t in [*specialist_tasks, command]], tasks=[*specialist_tasks, command],
                    process=Process.sequential, verbose=False)

    def inputs(self, action: str) -> dict:
        r = self.report
        dump = lambda row: json.dumps([row], indent=1)
        return {
            "sector": r["sector"], "action": action, "doctrine": doctrine(),
            "sensor_slice": dump({"sector": r["sector"], "sensors": r["sensors"], "containment_state": r["containment_state"]}),
            "sighting_slice": dump({"sector": r["sector"], "sighting": r.get("sighting")}),
            "civilian_slice": dump({"sector": r["sector"], "civilian_status": r["civilian_status"],
                                    "containment_state": r["containment_state"]}),
        }
