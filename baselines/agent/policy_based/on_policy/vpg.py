import numpy as np
import torch, torch.nn.functional as F
from torch.optim import Adam
from baselines.common.policy import OnPolicyAlgorithm
from baselines.common.network import MLPGaussianPolicy, MLPGaussianSDEPolicy, MLPVFunction


class VPG(OnPolicyAlgorithm):
    def __init__(self, env, **config):
        super().__init__(
            env=env,
            actor_size=config.get('actor_size', (64, 64)),
            critic_size=config.get('critic_size', (64, 64)),
            actor_activation=config.get('actor_activation', torch.tanh),
            critic_activation=config.get('critic_activation', torch.tanh),
            buffer_size=config.get('buffer_size', int(1e+6)),
            update_after=config.get('update_after', 128),
            actor_lr=config.get('actor_lr', 3e-4),
            critic_lr=config.get('critic_lr', 3e-4),
            gamma=config.get('gamma', 0.99),
            lmda=config.get('lmda', 0.95),
            vf_coef=None,   
            ent_coef=None,          
            reward_norm=config.get('reward_norm', False),
            adv_norm=config.get('adv_norm', False)
        )

        self.vf_iters = config.get('vf_iters', 10)
        self.gsde_mode = config.get('gsde_mode', False)
        self.config = config

        if self.gsde_mode:
            self.actor = MLPGaussianSDEPolicy(
                self.state_dim, 
                self.action_dim, 
                self.actor_size, 
                self.actor_activation
                ).to(self.device)
        else:
            self.actor = MLPGaussianPolicy(
                self.state_dim, 
                self.action_dim, 
                self.actor_size, 
                self.actor_activation
                ).to(self.device)
        
        self.critic = MLPVFunction(
            self.state_dim, 
            self.critic_size, 
            self.critic_activation
            ).to(self.device)

        self.actor_optim = Adam(self.actor.parameters(), lr=self.actor_lr)
        self.critic_optim = Adam(self.critic.parameters(), lr=self.critic_lr)

    @torch.no_grad()
    def act(self, state, training=True, global_buffer_size=None):
        self.actor.train(training)
        state = torch.FloatTensor(state).to(self.device)
        mu, std = self.actor(state)

        if self.gsde_mode:
            dist = self.actor.dist(state)
            action = dist.sample() if training else mu
            return torch.tanh(action + self.actor.get_noise()).cpu().numpy()
        else:
            action = torch.normal(mu, std) if training else mu
            return torch.tanh(action).cpu().numpy()
        
    def learn(self, states, actions, rewards, next_states, dones):
        self.actor.train()
        self.critic.train()

        if self.gsde_mode:
            self.actor.reset_noise()
            
        with torch.no_grad():
            values, next_values = self.critic(states), self.critic(next_states)
            rets, advs = self.GAE(values, next_values, rewards, dones)

        log_probs = self.actor.log_prob(states, actions)
        actor_loss = -(log_probs * advs).mean()

        self.actor_optim.zero_grad()
        actor_loss.backward()
        self.actor_optim.step()

        critic_losses = []
        for _ in range(self.vf_iters):
            critic_loss = F.mse_loss(self.critic(states), rets)
            self.critic_optim.zero_grad()
            critic_loss.backward()
            self.critic_optim.step()
            critic_losses.append(critic_loss.item())

        entropy = self.actor.entropy(states)
        result = {
            'agent_timesteps': self.timesteps, 
            'actor_loss': actor_loss.item(), 
            'critic_loss': np.mean(critic_losses), 
            'entropy': entropy.item()
            }
                
        return result
    
    def save(self, save_path):
        torch.save({
            'actor_state_dict': self.actor.state_dict(),
            'critic_state_dict': self.critic.state_dict(),
            'actor_optim_state_dict': self.actor_optim.state_dict(),
            'critic_optim_state_dict': self.critic_optim.state_dict()
        }, save_path)

    def load(self, load_path):
        checkpoint = torch.load(load_path, weights_only=True)
        self.actor.load_state_dict(checkpoint['actor_state_dict'])
        self.critic.load_state_dict(checkpoint['critic_state_dict'])
        self.actor_optim.load_state_dict(checkpoint['actor_optim_state_dict'])
        self.critic_optim.load_state_dict(checkpoint['critic_optim_state_dict'])