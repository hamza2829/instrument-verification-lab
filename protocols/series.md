# Protocol P-SERIES: Series build verification

Build: series

Preconditions: instrument powered, firmware for the series build installed, tester signed in.
Record for each step: result (pass/fail), observed value, evidence reference.

| Step | Req | Action | Expected | Evidence | Auto |
|---|---|---|---|---|---|
| A01 | REQ-001 | Load sample S001, start a run, stop it | Run COMPLETED, state IDLE | Run id and status | run_lifecycle |
| A02 | REQ-002 | Start a run with an empty rack | Start rejected | Rejection message | start_requires_sample |
| A03 | REQ-003 | Load 8 samples, then a 9th | 8 accepted, 9th rejected | Rack count | sample_capacity |
| A04 | REQ-004 | Run and read temperature 10 times | All reads within 37.0 +/- 0.5 C | Max deviation | temp_stability |
| A05 | REQ-005 | Inject over-temperature during a run | E101, run ABORTED | State, error, run status | overtemp_alarm |
| A06 | REQ-006 | Open the door during a run | E103, run ABORTED | State, error, run status | door_interlock |
| A07 | REQ-007 | Disconnect the temperature sensor during a run | E102, run ABORTED | State, error, run status | sensor_dropout |
| A08 | REQ-008 | Clear faults after E101, reset, start a new run | State RUNNING | State after reset | error_recovery |
| A09 | REQ-009 | Complete three runs | 3 COMPLETED rows in database | Row count | results_persistence |
| A10 | REQ-010 | Load, start, stop | Events logged for each action | Event list | audit_log |
| M01 | REQ-011 | Visual check of the operator console during a run | State RUNNING and samples shown | Screenshot | - |
| M02 | REQ-011 | Trigger E101 and look at the console | Error code and text shown in red | Screenshot | - |
| M03 | REQ-012 | Inspect rack position labels | Labels 1-8 present and readable | Photo | - |
