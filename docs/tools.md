# Scenario MCP tools

Server: `https://api.you.com/mcp/halloween-hack-26` (streamable HTTP, no auth headers)

## `hack26-list-scenarios`

List the available scenario feeds and how many ticks each one has.

```json
{
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {}
}
```

## `hack26-get-tick`

Pull the next incident tick for your team. The cursor advances per team; when the feed is exhausted the last tick repeats with exhausted: true.

```json
{
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {
    "team": {
      "type": "string",
      "minLength": 2,
      "maxLength": 32,
      "pattern": "^[a-z0-9][a-z0-9-]*$",
      "description": "Your team handle from the welcome card, e.g. team-04."
    },
    "token": {
      "description": "Team token from your card. Only needed if the organizers enabled tokens.",
      "type": "string",
      "maxLength": 128
    },
    "scenario": {
      "type": "string",
      "enum": [
        "outbreak-level-5",
        "control-tick"
      ],
      "description": "Which feed to pull from."
    }
  },
  "required": [
    "team",
    "scenario"
  ]
}
```

## `hack26-submit-containment`

Report the action your swarm chose for a tick. One accepted answer per tick per team: repeats return the original judgment with duplicate: true.

```json
{
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {
    "team": {
      "type": "string",
      "minLength": 2,
      "maxLength": 32,
      "pattern": "^[a-z0-9][a-z0-9-]*$",
      "description": "Your team handle from the welcome card, e.g. team-04."
    },
    "token": {
      "description": "Team token from your card. Only needed if the organizers enabled tokens.",
      "type": "string",
      "maxLength": 128
    },
    "tick_id": {
      "type": "integer",
      "exclusiveMinimum": 0,
      "maximum": 9007199254740991,
      "description": "The tick your decision answers."
    },
    "action": {
      "type": "string",
      "enum": [
        "contain",
        "evacuate",
        "observe"
      ],
      "description": "The action your swarm took."
    }
  },
  "required": [
    "team",
    "tick_id",
    "action"
  ]
}
```

## `hack26-get-scoreboard`

Current standings: submissions, total score, and false alarms per team.

```json
{
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {}
}
```

## `hack26-ask-oracle`

Ask a lore or doctrine question about the scenario. Advisory only: never scored, never affects your containment result.

```json
{
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {
    "question": {
      "type": "string",
      "minLength": 3,
      "maxLength": 500,
      "description": "What you want to know (short: this is a fortune cookie, not a research desk)."
    }
  },
  "required": [
    "question"
  ]
}
```

## `hack26-list-scenarios` response

```
{
  "scenarios": [
    {
      "name": "outbreak-level-5",
      "ticks": 2
    },
    {
      "name": "control-tick",
      "ticks": 1
    }
  ]
}
```

## `hack26-get-scoreboard` response (at probe time)

```
{
  "teams": [
    {
      "team": "team-hollow-lantern-08",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test2",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test3",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test5",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "agentgeist",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test4",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test6",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "agent-doom",
      "submissions": 3,
      "total_score": 3,
      "false_alarms": 0
    },
    {
      "team": "team-crimson-raven",
      "submissions": 3,
      "total_score": 2.5,
      "false_alarms": 0
    },
    {
      "team": "agentgeist-test2",
      "submissions": 2,
      "total_score": 2,
      "false_alarms": 0
    },
    {
      "team": "agentgeist-test",
      "submissions": 2,
      "total_score": 2,
      "false_alarms": 0
    },
    {
      "team": "team-dry-run",
      "submissions": 2,
      "total_score": 2,
      "false_alarms": 0
    },
    {
      "team": "team-markus-test",
      "submissions": 3,
      "total_score": 1,
      "false_alarms": 0
    }
  ]
}
```
