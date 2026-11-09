# Use LangGraph as the only workflow engine

The control plane needs explicit states, a retry limit, and a place to stop for a person. LangGraph is already a dependency, so it is the state machine. Task state is also stored in the database, which is what a restart reads. Temporal is not added in this version.
