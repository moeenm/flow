"""Figure eight example."""

import json
import random

import ray
import ray.rllib.agents.ppo as ppo
from ray.rllib.agents.ppo.ppo_policy_graph import PPOPolicyGraph
from ray.tune import run_experiments
from ray import tune
from ray.tune.registry import register_env

from flow.utils.registry import make_create_env
from flow.utils.rllib import FlowParamsEncoder
from flow.core.params import SumoParams, EnvParams, InitialConfig, NetParams
from flow.core.vehicles import Vehicles
from flow.controllers import IDMController, ContinuousRouter, RLController
from flow.scenarios.figure8.figure8_scenario import ADDITIONAL_NET_PARAMS

import gym

# time horizon of a single rollout
HORIZON = 1500
# number of rollouts per training iteration
N_ROLLOUTS = 2
# number of parallel workers
N_CPUS = 1

# We place one autonomous vehicle and 13 human-driven vehicles in the network
vehicles = Vehicles()
vehicles.add(
    veh_id="human",
    acceleration_controller=(IDMController, {
        "noise": 0.2
    }),
    routing_controller=(ContinuousRouter, {}),
    speed_mode="no_collide",
    num_vehicles=13)
vehicles.add(
    veh_id="rl",
    acceleration_controller=(RLController, {}),
    routing_controller=(ContinuousRouter, {}),
    speed_mode="no_collide",
    num_vehicles=1)

flow_params = dict(
    # name of the experiment
    exp_tag="figure_eight_intersection_control",

    # name of the flow environment the experiment is running on
    env_name="MultiAgentAccelEnv",

    # name of the scenario class the experiment is running on
    scenario="Figure8Scenario",

    # name of the generator used to create/modify network configuration files
    generator="Figure8Generator",

    # sumo-related parameters (see flow.core.params.SumoParams)
    sumo=SumoParams(
        sim_step=0.1,
        render=False,
    ),

    # environment related parameters (see flow.core.params.EnvParams)
    env=EnvParams(
        horizon=HORIZON,
        additional_params={
            "target_velocity": 20,
            "max_accel": 3,
            "max_decel": 3,
        },
    ),

    # network-related parameters (see flow.core.params.NetParams and the
    # scenario's documentation or ADDITIONAL_NET_PARAMS component)
    net=NetParams(
        no_internal_links=False,
        additional_params=ADDITIONAL_NET_PARAMS,
    ),

    # vehicles to be placed in the network at the start of a rollout (see
    # flow.core.vehicles.Vehicles)
    veh=vehicles,

    # parameters specifying the positioning of vehicles upon initialization/
    # reset (see flow.core.params.InitialConfig)
    initial=InitialConfig(),
)

if __name__ == "__main__":
    ray.init(num_cpus=4, redirect_output=False)

    config = ppo.DEFAULT_CONFIG.copy()
    config["num_workers"] = N_CPUS
    config["train_batch_size"] = HORIZON * N_ROLLOUTS
    config["simple_optimizer"] = True
    # config["gamma"] = 0.999  # discount rate
    # config["model"].update({"fcnet_hiddens": [100, 50, 25]})
    # config["use_gae"] = True
    # config["lambda"] = 0.97
    # config["sgd_batchsize"] = min(16 * 1024, config["timesteps_per_batch"])
    # config["kl_target"] = 0.02
    # config["num_sgd_iter"] = 10
    # config["horizon"] = HORIZON
    config["observation_filter"] = "NoFilter"

    # save the flow params for replay
    flow_json = json.dumps(
        flow_params, cls=FlowParamsEncoder, sort_keys=True, indent=4)
    config['env_config']['flow_params'] = flow_json

    create_env, env_name = make_create_env(params=flow_params, version=0)

    # Register as rllib env
    register_env(env_name, create_env)

    test_env = create_env()
    obs_space = test_env.observation_space
    act_space = test_env.action_space

    # def gen_policy():
    #     return (PGPolicyGraph, obs_space, act_space, {})
    #
    # policy_graphs = {}
    # policy_graphs["av"] = gen_policy()
    # policy_graphs["adversary"] = gen_policy()

    def gen_policy():
        return (PPOPolicyGraph, obs_space, act_space, {})

    # Setup PG with an ensemble of `num_policies` different policy graphs
    policy_graphs = {
        "policy_{}".format(i): gen_policy()
        for i in range(2)
    }


    def policy_mapping_fn(agent_id):
        import ipdb; ipdb.set_trace()
        # if agent_id % 2 == 0:
        #     return "av"
        # else:
        #     return "adversary"
        return agent_id

    policy_ids = list(policy_graphs.keys())
    config.update({"multiagent": {
                    "policy_graphs": policy_graphs,
                    "policy_mapping_fn": tune.function(
                        lambda agent_id: random.choice(policy_ids))
                }})

    run_experiments({
        "test": {
            "run": "PPO",
            "env": env_name,
            "stop": {
                "training_iteration": 1
            },
            "config": config,
            },
    })