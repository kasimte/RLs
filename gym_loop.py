import numpy as np


def get_action_normalize_factor(space, action_type):
    '''
    input: {'low': [-2, -3], 'high': [2, 6]}, 'continuous'
    return: [0, 1.5], [2, 4.5]
    '''
    if action_type == 'continuous':
        return (space.high + space.low) / 2, (space.high - space.low) / 2
    else:
        return 0, 1


def maybe_one_hot(obs, obs_space, n):
    """
    input: [[1, 0], [2, 1]], (3, 4), 2
    output: [[0. 0. 0. 0. 1. 0. 0. 0. 0. 0. 0. 0.]
             [0. 0. 0. 0. 0. 0. 0. 0. 0. 1. 0. 0.]]
    """
    if hasattr(obs_space, 'n'):
        obs = obs.reshape(n, -1)
        dim = [int(obs_space.n)] if type(obs_space.n) == int or type(obs_space.n) == np.int32 else list(obs_space.n)    # 在CliffWalking-v0环境其类型为numpy.int32
        multiplication_factor = dim[1:] + [1]
        n = np.array(dim).prod()
        ints = obs.dot(multiplication_factor)
        x = np.zeros([obs.shape[0], n])
        for i, j in enumerate(ints):
            x[i, j] = 1
        return x
    else:
        return obs


def init_variables(env, action_type):
    """
    inputs:
        env: Environment
        action_type: discrete or continuous
    outputs:
        i: specify which item of state should be modified
        mu: action bias
        sigma: action scale
        state: [vector_obs, visual_obs]
        newstate: [vector_obs, visual_obs]
    """
    i = 1 if len(env.observation_space.shape) == 3 else 0
    mu, sigma = get_action_normalize_factor(env.action_space, action_type)
    return i, mu, sigma, [np.empty(env.n), np.array([[]] * env.n)], [np.empty(env.n), np.array([[]] * env.n)]


class Loop(object):

    @staticmethod
    def train(env, gym_model, action_type, begin_episode, save_frequency, max_step, max_episode, eval_while_train, max_eval_episode, render, render_episode, policy_mode):
        """
        Inputs:
            env:                gym environment
            gym_model:          algorithm model
            action_type:        specify action type, discrete action space or continuous action space
            begin_episode:      initial episode
            save_frequency:     how often to save checkpoints
            max_step:           maximum number of steps in an episode
            max_episode:        maximum number of episodes in this training task
            render:             specify whether render the env or not
            render_episode:     if 'render' is false, specify from which episode to render the env
        """
        i, mu, sigma, state, new_state = init_variables(env, action_type)
        for episode in range(begin_episode, max_episode):
            obs = env.reset()
            state[i] = maybe_one_hot(obs, env.observation_space, env.n)
            dones_flag = np.full(env.n, False)
            step = 0
            r = np.zeros(env.n)
            last_done_step = -1
            while True:
                step += 1
                r_tem = np.zeros(env.n)
                if render or episode > render_episode:
                    env.render()
                action = gym_model.choose_action(s=state[0], visual_s=state[1])
                obs, reward, done, info = env.step(action * sigma + mu)
                unfinished_index = np.where(dones_flag == False)[0]
                dones_flag += done
                new_state[i] = maybe_one_hot(obs, env.observation_space, env.n)
                r_tem[unfinished_index] = reward[unfinished_index]
                r += r_tem
                gym_model.store_data(
                    s=state[0],
                    visual_s=state[1],
                    a=action,
                    r=reward,
                    s_=new_state[0],
                    visual_s_=new_state[1],
                    done=done
                )

                if all(dones_flag):
                    if last_done_step == -1:
                        last_done_step = step
                    if policy_mode == 'off-policy':
                        break

                if step >= max_step:
                    break

                if len(env.dones_index):    # 判断是否有线程中的环境需要局部reset
                    new_episode_states = maybe_one_hot(env.patial_reset(), env.observation_space, len(env.dones_index))
                    new_state[i][env.dones_index] = new_episode_states
                state[i] = new_state[i]

            gym_model.learn(episode=episode, step=step)
            gym_model.writer_summary(
                episode,
                total_reward=r.mean(),
                step=last_done_step
            )
            print('-' * 40)
            print(f'Episode: {episode:3d} | step: {step:4d} | last_done_step {last_done_step:4d} | rewards: {r}')
            if episode % save_frequency == 0:
                gym_model.save_checkpoint(episode)

            if eval_while_train and env.reward_threshold is not None:
                if r.max() >= env.reward_threshold:
                    ave_r, ave_step = Loop.evaluate(env, gym_model, action_type, max_step, max_eval_episode)
                    solved = True if ave_r >= env.reward_threshold else False
                    print(f'-------------------------------------------Evaluate episode: {episode:3d}--------------------------------------------------')
                    print(f'evaluate number: {max_eval_episode:3d} | average step: {ave_step} | average reward: {ave_r} | SOLVED: {solved}')
                    print('----------------------------------------------------------------------------------------------------------------------------')

    @staticmethod
    def evaluate(env, gym_model, action_type, max_step, max_eval_episode):
        i, mu, sigma, state, _ = init_variables(env, action_type)
        total_r = np.zeros(env.n)
        total_steps = np.zeros(env.n)
        episodes = max_eval_episode // env.n
        for _ in range(episodes):
            obs = env.reset()
            state[i] = maybe_one_hot(obs, env.observation_space, env.n)
            dones_flag = np.full(env.n, False)
            steps = np.zeros(env.n)
            r = np.zeros(env.n)
            while True:
                r_tem = np.zeros(env.n)
                action = gym_model.choose_inference_action(s=state[0], visual_s=state[1])
                obs, reward, done, info = env.step(action * sigma + mu)
                unfinished_index = np.where(dones_flag == False)
                dones_flag += done
                state[i] = maybe_one_hot(obs, env.observation_space, env.n)
                r_tem[unfinished_index] = reward[unfinished_index]
                steps[unfinished_index] += 1
                r += r_tem
                if all(dones_flag) or any(steps >= max_step):
                    break
            total_r += r
            total_steps += steps
        average_r = total_r.mean() / episodes
        average_step = int(total_steps.mean() / episodes)
        return average_r, average_step

    @staticmethod
    def inference(env, gym_model, action_type):
        """
        inference mode. algorithm model will not be train, only used to show agents' behavior
        """
        i, mu, sigma, state, _ = init_variables(env, action_type)
        while True:
            obs = env.reset()
            state[i] = maybe_one_hot(obs, env.observation_space, env.n)
            while True:
                env.render()
                action = gym_model.choose_inference_action(s=state[0], visual_s=state[1])
                obs, reward, done, info = env.step(action * sigma + mu)
                state[i] = maybe_one_hot(obs, env.observation_space, env.n)
                if len(env.dones_index):    # 判断是否有线程中的环境需要局部reset
                    new_episode_states = maybe_one_hot(env.patial_reset(), env.observation_space, len(env.dones_index))
                    state[i][env.dones_index] = new_episode_states

    @staticmethod
    def no_op(env, gym_model, action_type, steps, choose=False):
        assert type(steps) == int and steps >= 0, 'no_op.steps must have type of int and larger than/equal 0'
        i, mu, sigma, state, new_state = init_variables(env, action_type)

        obs = env.reset()
        state[i] = maybe_one_hot(obs, env.observation_space, env.n)

        steps = steps // env.n + 1

        for step in range(steps):
            print(f'no op step {step}')
            if choose:
                action = gym_model.choose_action(s=state[0], visual_s=state[1])
                obs, reward, done, info = env.step(action * sigma + mu)
            else:
                action = env.sample_action()
                obs, reward, done, info = env.step(action)
            new_state[i] = maybe_one_hot(obs, env.observation_space, env.n)
            gym_model.no_op_store(
                s=state[0],
                visual_s=state[1],
                a=action,
                r=reward,
                s_=new_state[0],
                visual_s_=new_state[1],
                done=done
            )
            if len(env.dones_index):    # 判断是否有线程中的环境需要局部reset
                new_episode_states = maybe_one_hot(env.patial_reset(), env.observation_space, len(env.dones_index))
                new_state[i][env.dones_index] = new_episode_states
            state[i] = new_state[i]
