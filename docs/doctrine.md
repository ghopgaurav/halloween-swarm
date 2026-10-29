# Doctrine (from hack26-ask-oracle)

Verbatim oracle answers. The commander and the safety gate follow these; nothing here is invented.

## Q: What is the official doctrine for choosing contain vs evacuate vs observe?

{
  "configured": true,
  "question": "What is the official doctrine for choosing contain vs evacuate vs observe?",
  "answered": false,
  "status": 400,
  "answer": "The oracle could not answer just now. Carry on — it is advisory only."
}

## Q: When should a team escalate to the Discord channel, and when is it a false alarm?

{
  "configured": true,
  "question": "When should a team escalate to the Discord channel, and when is it a false alarm?",
  "answered": true,
  "answer": "Escalate to Discord: confirmed haunting halts coding, safety hazard, team locked out, judging/scoring platform down.\n\nFalse alarm: flickering lights, whispers, cold spots, brief glitch fixed by reset.\n\nLog false alarms locally. Escalate only blockers and hazards. Rules and scoring unchanged."
}

## Q: What does a harmless control tick look like?

{
  "configured": true,
  "question": "What does a harmless control tick look like?",
  "answered": false,
  "answer": "The oracle had nothing to say. Carry on — it is advisory only."
}

## Q: How should a swarm treat low-confidence residual echoes or sensor faults?

{
  "configured": true,
  "question": "How should a swarm treat low-confidence residual echoes or sensor faults?",
  "answered": false,
  "status": 400,
  "answer": "The oracle could not answer just now. Carry on — it is advisory only."
}

## Q: How does the feed signal that there are no more ticks?

{
  "configured": true,
  "question": "How does the feed signal that there are no more ticks?",
  "answered": false,
  "answer": "The oracle had nothing to say. Carry on — it is advisory only."
}

# Second pass (short questions; all answered)

The oracle is generative and advisory: answers vary between calls. Treat the distilled rules below as the doctrine.

## Q: When do we evacuate a sector?

Evacuate sector immediately on Oracle order, alarm activation, or confirmed apparition breach. Drop tasks. Seal doors. Move to lobby muster. No re-entry until all-clear.

## Q: When do we contain?

Briefing: Contain at first confirmed manifestation. Seal floor, kill lights, hold position. No re-entry after containment.

## Q: When do we observe?

Observation: Halloween night, October 31, after dark. Be inside before lock-in.

## Q: Is a residual-echo dangerous?

Negative. Residual-echo: passive replay loop. No sentience, no interaction, no physical danger. Observe, log, proceed.

## Q: What is a level-5-phantom?

Level-5 phantom: maximum threat. Unbound, floor-independent. Breaches locked rooms, kills power, rewrites files, mimics staff voices. Solo contact prohibited. Report location, retreat to lit stairwell, await full containment team.

## Q: What counts as over-escalation?

Over-escalation: Response exceeding verified threat.

Counts: Full lockdown for unconfirmed noises. Evacuation without visual confirmation. Lethal or occult countermeasures on ambiguous readings. Building-wide alert for localized anomaly. Expenditures of limited supplies without confirmed contact.

Standard: Verify first. Match action to contact, proximity, harm. Escalate stepwise.

# Distilled doctrine (what the commander and safety gate enforce)

Each rule cites the oracle answer above it came from.

1. **Evacuate** a sector on a *confirmed apparition breach* (containment_state `breached` with a
   credible hostile sighting). Pinned civilians in a breached sector make evacuation mandatory and
   are a *safety hazard*, which is an escalation trigger. (Q: When do we evacuate; Q: When should a team escalate)
2. **Contain** at the first *confirmed manifestation* that has not breached and has no civilians at risk.
   (Q: When do we contain)
3. **Observe** residual echoes, ambiguous readings and benign activity: "passive replay loop... Observe, log, proceed".
   (Q: Is a residual-echo dangerous)
4. **No over-escalation**: no evacuation without visual confirmation, no building-wide alert for a localized
   anomaly. Verify first, match action to contact, proximity and harm, escalate stepwise. (Q: What counts as over-escalation)
5. **Escalate to Discord only for hazards and blockers**; log false alarms locally (cold spots, whispers,
   flickers). (Q: When should a team escalate)
6. A **level-5-phantom** is maximum threat; report location, do not engage solo. (Q: What is a level-5-phantom)
