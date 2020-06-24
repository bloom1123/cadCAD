from copy import deepcopy
from typing import Dict, Callable, List, Tuple
from functools import reduce
import pandas as pd
from pandas.core.frame import DataFrame

from cadCAD import configs
from cadCAD.utils import key_filter
from cadCAD.configuration.utils import exo_update_per_ts
from cadCAD.configuration.utils.depreciationHandler import sanitize_partial_state_updates, sanitize_config


class Configuration(object):
    def __init__(self, user_id, sim_config={}, initial_state={}, seeds={}, env_processes={},
                 exogenous_states={}, partial_state_update_blocks={}, policy_ops=[lambda a, b: a + b],
                 session_id=0, simulation_id=0, run_id=1, **kwargs) -> None:
        # print(exogenous_states)
        self.sim_config = sim_config
        self.initial_state = initial_state
        self.seeds = seeds
        self.env_processes = env_processes
        self.exogenous_states = exogenous_states
        self.partial_state_updates = partial_state_update_blocks
        self.policy_ops = policy_ops
        self.kwargs = kwargs

        self.user_id = user_id
        self.session_id = session_id
        self.simulation_id = simulation_id
        self.run_id = run_id

        sanitize_config(self)


def append_configs(
    user_id='cadCAD_user',
    session_id=0, #ToDo: change to string
    sim_configs={}, initial_state={}, seeds={}, raw_exogenous_states={}, env_processes={},
    partial_state_update_blocks={}, policy_ops=[lambda a, b: a + b], _exo_update_per_ts: bool = True,
    config_list=configs
                  ) -> None:
    if _exo_update_per_ts is True:
        exogenous_states = exo_update_per_ts(raw_exogenous_states)
    else:
        exogenous_states = raw_exogenous_states

    if isinstance(sim_configs, dict):
        sim_configs = [sim_configs]

    simulation_id = 0
    if len(config_list) > 0:
        last_config = config_list[-1]
        simulation_id = last_config.simulation_id + 1

    sim_cnt = 0
    new_sim_configs = []
    for t in list(zip(sim_configs, list(range(len(sim_configs))))):
        sim_config = t[0]
        N = sim_config['N']

        if N > 1:
            for n in range(N):
                sim_config['simulation_id'] = simulation_id + sim_cnt
                sim_config['run_id'] = n
                sim_config['N'] = 1
                # sim_config['N'] = n + 1
                new_sim_configs.append(deepcopy(sim_config))
            del sim_config
        else:
            sim_config['simulation_id'] = simulation_id
            sim_config['run_id'] = 0
            new_sim_configs.append(deepcopy(sim_config))

        sim_cnt += 1

    # for sim_config in sim_configs:
    for sim_config in new_sim_configs:
        config = Configuration(
            sim_config=sim_config,
            initial_state=initial_state,
            seeds=seeds,
            exogenous_states=exogenous_states,
            env_processes=env_processes,
            partial_state_update_blocks=partial_state_update_blocks,
            policy_ops=policy_ops,

            # session_id=session_id,
            user_id=user_id,
            session_id=f"{user_id}={sim_config['simulation_id']}_{sim_config['run_id']}",
            simulation_id=sim_config['simulation_id'],
            run_id=sim_config['run_id']
        )
        configs.append(config)


class Identity:
    def __init__(self, policy_id: Dict[str, int] = {'identity': 0}) -> None:
        self.beh_id_return_val = policy_id

    def p_identity(self, var_dict, sub_step, sL, s, **kwargs):
        return self.beh_id_return_val

    def policy_identity(self, k: str) -> Callable:
        return self.p_identity

    def no_state_identity(self, var_dict, sub_step, sL, s, _input, **kwargs):
        return None

    def state_identity(self, k: str) -> Callable:
        return lambda var_dict, sub_step, sL, s, _input, **kwargs: (k, s[k])

    # state_identity = cloudpickle.dumps(state_identity)

    def apply_identity_funcs(self, identity: Callable, df: DataFrame, cols: List[str]) -> List[DataFrame]:
        # identity = pickle.loads(identity)
        def fillna_with_id_func(identity, df, col):
            return df[[col]].fillna(value=identity(col))

        return list(map(lambda col: fillna_with_id_func(identity, df, col), cols))


class Processor:
    def __init__(self, id: Identity = Identity()) -> None:
        self.id = id
        self.p_identity = id.p_identity
        self.policy_identity = id.policy_identity
        self.no_state_identity = id.no_state_identity
        self.state_identity = id.state_identity
        self.apply_identity_funcs = id.apply_identity_funcs

    def create_matrix_field(self, partial_state_updates, key: str) -> DataFrame:
        if key == 'variables':
            identity = self.state_identity
        elif key == 'policies':
            identity = self.policy_identity

        df = pd.DataFrame(key_filter(partial_state_updates, key))
        col_list = self.apply_identity_funcs(identity, df, list(df.columns))
        if len(col_list) != 0:
            return reduce((lambda x, y: pd.concat([x, y], axis=1)), col_list)
        else:
            return pd.DataFrame({'empty': []})

    def generate_config(self, initial_state, partial_state_updates, exo_proc
                       ) -> List[Tuple[List[Callable], List[Callable]]]:

        def no_update_handler(bdf, sdf):
            if (bdf.empty == False) and (sdf.empty == True):
                bdf_values = bdf.values.tolist()
                sdf_values = [[self.no_state_identity] * len(bdf_values) for m in range(len(partial_state_updates))]
                return sdf_values, bdf_values
            elif (bdf.empty == True) and (sdf.empty == False):
                sdf_values = sdf.values.tolist()
                bdf_values = [[self.p_identity] * len(sdf_values) for m in range(len(partial_state_updates))]
                return sdf_values, bdf_values
            else:
                sdf_values = sdf.values.tolist()
                bdf_values = bdf.values.tolist()
                return sdf_values, bdf_values

        def only_ep_handler(state_dict):
            sdf_functions = [
                lambda var_dict, sub_step, sL, s, _input, **kwargs: (k, v) for k, v in zip(state_dict.keys(), state_dict.values())
            ]
            sdf_values = [sdf_functions]
            bdf_values = [[self.p_identity] * len(sdf_values)]
            return sdf_values, bdf_values

        if len(partial_state_updates) != 0:
            # backwards compatibility #
            partial_state_updates = sanitize_partial_state_updates(partial_state_updates)

            bdf = self.create_matrix_field(partial_state_updates, 'policies')
            sdf = self.create_matrix_field(partial_state_updates, 'variables')
            sdf_values, bdf_values = no_update_handler(bdf, sdf)
            zipped_list = list(zip(sdf_values, bdf_values))
        else:
            sdf_values, bdf_values = only_ep_handler(initial_state)
            zipped_list = list(zip(sdf_values, bdf_values))

        return list(map(lambda x: (x[0] + exo_proc, x[1]), zipped_list))

# from time import time
# def timing_val(func):
#     def wrapper(*arg, **kw):
#         '''source: http://www.daniweb.com/code/snippet368.html'''
#         t1 = time()
#         res = func(*arg, **kw)
#         t2 = time()
#         print(f"{func.__name__}: {t2-t1 :.5f}")
#         return res
#     return wrapper
