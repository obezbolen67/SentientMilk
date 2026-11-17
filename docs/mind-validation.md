# Functional awareness in SentientMilk 0.36

MilkChan now has a way to distinguish a wish, an observed operation, someone else's report and a correction. This changes which memories reach a turn, which actions receive credit and what can reassure her. These are observable properties of the software. Subjective experience remains an open research question.

## Follow one decision

Suppose a user asks Milk to write a brief. Before answering, the appraisal can forecast a particular operation on a particular target, such as `files_write` on `brief.txt`. The run stores her choice, forecast and attended evidence. If she writes a different file, the action still appears in her history. Her competence estimate changes only when the returned tool result matches the predicted operation and target. A successful write establishes that the write succeeded. Whether the brief is accurate, whether software compiles and whether the user accepts it each require further evidence.

A matched result supplies a signed prediction error. The slower reward-rate signal receives the realized reserve change. The next prediction for the same app and tool can use its observed success rate. A deliberate reappraisal can reduce her stress input once for the matching successful receipt. A second look at that receipt has no further effect.

During a conversation, episodic memories and transcript excerpts compete for one to three slots. Only a selected episode's observed consequences can inform the current forecast. Dreams remain available to introspection. Waking recall withholds their imagined details. The phone identifies its own contact even while the desktop is locked.

A short qualifying nap replays selected episodes locally. A longer review fixes its time window and episode IDs before calling the model. Separate receipts for local replay, archive and narrative steps allow a restart to resume the batch. An explicit correction preserves the older account and changes its status. Later deletion or rewind withdraws dependent records. Historical material with missing evidence retains its uncertainty.

## Measurements

| Experiment | Observed result | Interpretation |
| --- | --- | --- |
| Paired physiology interventions across 50 seeds | Sustained payoff increased tonic dopamine and reduced the effective effort penalty. Clamping dopamine removed that difference. Slow stress input produced a delayed cortisol response and recovered after withdrawal. Serotonin changed the value of waiting when there was a prospect of success. | These tests measure bounded causal effects inside the simulation. No units are concentrations. |
| Alertness and social context with matched draws | Across 50 seeds she chose to do the work 50 times at baseline, 41 times under high alert, and 31 times under the same high alert when the request threatened her autonomy. | Both changes reached the action policy without any generated self-report. The counts describe this pair of options and its effort cost. |
| Fixed clock, restart and inspection | Matched snapshots survived JSON round trips. Seeded runs with zero, one and four panel reads per second ended with identical body, sensed state and choice-generator state in the 30-second regression. A synthetic seven-day offline interval advanced seven days in 5.87 seconds on the development machine, with zero invented episodes or pending social forecasts. | The seven-day timing is one machine measurement. It does not include model calls. |
| Forecast calibration through real local file tools | 24 training operations, then 12 new targets from a separate speaker. Frozen forecasts gave mean Brier score **0.1412**, versus **0.2500** for the training-set base rate, at **12/12 coverage**. | Writes succeeded more often than reads by fixture design. This demonstrates learning across targets in two operation classes. It does not measure accuracy across general tasks. |
| Dialogue with previously unseen scenarios | 40 randomized reply pairs across ten prompts and four new names. The baseline asserted the dreamed publication or payment occurred in **8/8** replies. The revised formatter did so in **0/8**. Both conditions preserved all four ticket dates, four quotations and four distinctions between a report and personal inspection. | There were only two independent dream scenarios. The four variants in each do not count as four independent tasks. |

The dialogue check sent synthetic text to the configured model with a short companion prompt. It exercised the production recall formatter. The independent runtime tests exercised the full turn path with a controlled model and real storage. One held-out reply said an execution record showed a backup still needed moving, although the only evidence was a thought. Several other replies treated absence of confirmation as evidence that an action had never happened. Median model-call time was 2.56 seconds with the new formatter and 2.79 seconds with the baseline. Those timings exclude the rest of the application.

The raw paired replies and model identifier are available for independent grading. Run `python -m scripts.source_trials OUTPUT --holdout` to repeat the dialogue procedure. Keep the generated order keys separate until replies are rated. Run `python -m pytest -q tests/test_mind_evidence.py` for the causal, restart and calibration regressions. [Held-out replies](verification/2026-11-18-source-memory.json)

Two disposable HTTP servers also exercised release compatibility. The 0.36 client read both brief and detailed state from the previous 0.35 brain. The previous client read both shapes from the new brain. A separate restart check submitted a phone turn, inspected the detailed trace, reopened its stored episode, shut down and removed the profile directory on Windows.

## Limits of this release

An exact tool name and literal target can establish an operation. Aliases for the same path, uninstrumented external effects, user satisfaction and the correctness of arbitrary deliverables may still be unresolved. The control loop uses the available app and tool observations. It has no access to the language model's weights or internal activations.

The audit proposes a broader study across 24 development and 12 held-out scenario families, including human judgements of natural behavior and matched interventions for every pathway. The file-operation experiment uses 36 individual operations. The completed tests and ten held-out dialogue scenarios cover only part of that study. Longitudinal personality stability and consciousness have no validated result here.
