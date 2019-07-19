import pandas as pd
from tabulate import tabulate
# The following imports NEED to be in the exact order
from cadCAD.engine import ExecutionMode, ExecutionContext, Executor
from simulations.regression_tests import historical_state_access
from cadCAD import configs

exec_mode = ExecutionMode()

print("Simulation Execution: Single Configuration")
print()
first_config = configs # only contains config1
single_proc_ctx = ExecutionContext(context=exec_mode.single_proc)
run = Executor(exec_context=single_proc_ctx, configs=first_config)

raw_result, tensor_field = run.execute()
result = pd.DataFrame(raw_result)
# cols = ['run','substep','timestep','x','nonexsistant','last_x','2nd_to_last_x','3rd_to_last_x','4th_to_last_x']
cols = ['last_x']
result = result[cols]

print()
print("Tensor Field: config1")
print(tabulate(tensor_field, headers='keys', tablefmt='psql'))
print("Output:")
print(tabulate(result, headers='keys', tablefmt='psql'))
print()
