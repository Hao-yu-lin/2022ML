# -*- coding: utf-8 -*-
"""hw04.ipynb
Automatically generated by Colaboratory.
Original file is located at
    https://colab.research.google.com/drive/1gC2Gojv9ov9MUQ1a1WDpVBD6FOcLZsog
# Task description
- Classify the speakers of given features.
- Main goal: Learn how to use transformer.
- Baselines:
  - Easy: Run sample code and know how to use transformer.
  - Medium: Know how to adjust parameters of transformer.
  - Strong: Construct [conformer](https://arxiv.org/abs/2005.08100) which is a variety of transformer. 
  - Boss: Implement [Self-Attention Pooling](https://arxiv.org/pdf/2008.01077v1.pdf) & [Additive Margin Softmax](https://arxiv.org/pdf/1801.05599.pdf) to further boost the performance.
- Other links
  - Kaggle: [link](https://www.kaggle.com/t/ac77388c90204a4c8daebeddd40ff916)
  - Slide: [link](https://docs.google.com/presentation/d/1HLAj7UUIjZOycDe7DaVLSwJfXVd3bXPOyzSb6Zk3hYU/edit?usp=sharing)
  - Data: [link](https://drive.google.com/drive/folders/1vI1kuLB-q1VilIftiwnPOCAeOOFfBZge?usp=sharing)
# Download dataset
- Data is [here](https://drive.google.com/drive/folders/1vI1kuLB-q1VilIftiwnPOCAeOOFfBZge?usp=sharing)
"""

"""## Fix Random Seed"""


from re import S
import numpy as np
from sklearn.preprocessing import LabelEncoder
import torch
import random
import time

time_start = time.time()

def set_seed(seed):
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

set_seed(9103222)

"""# Data
## Dataset
- Original dataset is [Voxceleb2](https://www.robots.ox.ac.uk/~vgg/data/voxceleb/vox2.html).
- The [license](https://creativecommons.org/licenses/by/4.0/) and [complete version](https://www.robots.ox.ac.uk/~vgg/data/voxceleb/files/license.txt) of Voxceleb2.
- We randomly select 600 speakers from Voxceleb2.
- Then preprocess the raw waveforms into mel-spectrograms.
- Args:
  - data_dir: The path to the data directory.
  - metadata_path: The path to the metadata.
  - segment_len: The length of audio segment for training. 
- The architecture of data directory \\
  - data directory \\
  |---- metadata.json \\
  |---- testdata.json \\
  |---- mapping.json \\
  |---- uttr-{random string}.pt \\
- The information in metadata
  - "n_mels": The dimention of mel-spectrogram.
  - "speakers": A dictionary. 
    - Key: speaker ids.
    - value: "feature_path" and "mel_len"
For efficiency, we segment the mel-spectrograms into segments in the traing step.
"""

import os
import json
import torch
import random
from pathlib import Path
from torch.utils.data import Dataset
from torch.nn.utils.rnn import pad_sequence
 
 
class myDataset(Dataset):
	def __init__(self, data_dir, segment_len=128):
		self.data_dir = data_dir
		self.segment_len = segment_len
	
		# Load the mapping from speaker neme to their corresponding id. 
		mapping_path = Path(data_dir) / "mapping.json"
		mapping = json.load(mapping_path.open())
		self.speaker2id = mapping["speaker2id"]
	
		# Load metadata of training data.
		metadata_path = Path(data_dir) / "metadata.json"
		metadata = json.load(open(metadata_path))["speakers"]
	
		# Get the total number of speaker.
		self.speaker_num = len(metadata.keys())
		self.data = []
		for speaker in metadata.keys():
			for utterances in metadata[speaker]:
				self.data.append([utterances["feature_path"], self.speaker2id[speaker]])
 
	def __len__(self):
			return len(self.data)
 
	def __getitem__(self, index):
		feat_path, speaker = self.data[index]
		# Load preprocessed mel-spectrogram.
		mel = torch.load(os.path.join(self.data_dir, feat_path))

		# Segmemt mel-spectrogram into "segment_len" frames.
		if len(mel) > self.segment_len:
			# Randomly get the starting point of the segment.
			start = random.randint(0, len(mel) - self.segment_len)
			# Get a segment with "segment_len" frames.
			mel = torch.FloatTensor(mel[start:start+self.segment_len])
		else:
			mel = torch.FloatTensor(mel)
		# Turn the speaker id into long for computing loss later.
		speaker = torch.FloatTensor([speaker]).long()
		return mel, speaker
 
	def get_speaker_number(self):
		return self.speaker_num

"""## Dataloader
- Split dataset into training dataset(90%) and validation dataset(10%).
- Create dataloader to iterate the data.
"""

import torch
from torch.utils.data import DataLoader, random_split
from torch.nn.utils.rnn import pad_sequence


def collate_batch(batch):
	# Process features within a batch.
	"""Collate a batch of data."""
	mel, speaker = zip(*batch)
	# Because we train the model batch by batch, we need to pad the features in the same batch to make their lengths the same.
	mel = pad_sequence(mel, batch_first=True, padding_value=-20)    # pad log 10^(-20) which is very small value.
	# mel: (batch size, length, 40)
	return mel, torch.FloatTensor(speaker).long()


def get_dataloader(data_dir, batch_size, n_workers):
	"""Generate dataloader"""
	dataset = myDataset(data_dir)
	speaker_num = dataset.get_speaker_number()
	# Split dataset into training dataset and validation dataset
	trainlen = int(0.9 * len(dataset))
	lengths = [trainlen, len(dataset) - trainlen]
	trainset, validset = random_split(dataset, lengths)

	train_loader = DataLoader(
		trainset,
		batch_size=batch_size,
		shuffle=True,
		drop_last=True,
		num_workers=n_workers,
		pin_memory=True,
		collate_fn=collate_batch,
	)
	valid_loader = DataLoader(
		validset,
		batch_size=batch_size,
		num_workers=n_workers,
		drop_last=True,
		pin_memory=True,
		collate_fn=collate_batch,
	)

	return train_loader, valid_loader, speaker_num

"""# Model
- TransformerEncoderLayer:
  - Base transformer encoder layer in [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
  - Parameters:
    - d_model: the number of expected features of the input (required).
    - nhead: the number of heads of the multiheadattention models (required).
    - dim_feedforward: the dimension of the feedforward network model (default=2048).
    - dropout: the dropout value (default=0.1).
    - activation: the activation function of intermediate layer, relu or gelu (default=relu).
- TransformerEncoder:
  - TransformerEncoder is a stack of N transformer encoder layers
  - Parameters:
    - encoder_layer: an instance of the TransformerEncoderLayer() class (required).
    - num_layers: the number of sub-encoder-layers in the encoder (required).
    - norm: the layer normalization component (optional).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import sys
# sys.path.append('./Conformer')
# from CF import Conformer
import torchaudio

from torchsummary import summary






class Classifier(nn.Module):
	def __init__(self, 
				d_model=80, 
				num_heads = 5, 
				ffn_dim = 2048,
				num_layers = 3, 
				depthwise_conv_kernel_size = 3, 
				n_spks=600, 
				dropout=0.1, 
				s = 30.0, 
				m = 0.4):
		super().__init__()
		# Project the dimension of features from that of input into d_model.
		self.prenet = nn.Linear(40, d_model)

		self.encoder_conformer = torchaudio.models.Conformer(input_dim = d_model, 
											num_heads = num_heads,
											ffn_dim = ffn_dim,
											num_layers = num_layers,
											depthwise_conv_kernel_size = depthwise_conv_kernel_size,
											dropout = dropout)

		# self attention pooling
		self.softmax = nn.Softmax(dim = 1)
		self.weight = nn.Parameter(torch.rand(1, d_model))
		self.fc = nn.Linear(d_model, n_spks, bias = False).cuda()
		self.s = s
		self.m = m


	def forward(self, mels, labels = None, predict = False):
		"""
		args:
			mels: (batch size, length, 40)
		return:
			out: (batch size, n_spks)
		"""
		# out: (batch size, length, d_model)
		out = self.prenet(mels)
		lens = torch.tensor([out.size(1)] * out.size(0)).cuda()
		# out
		out, _lens = self.encoder_conformer(out, lens)
		
		# self attention pooling
		# 1 * d_model 
		weight = self.weight @ out.permute(0, 2, 1)		#out: (batch size, d_model, length)
		weight = self.softmax(weight)
		stats = (weight @ out).squeeze(1)	# stats: (batch size, length)

        # https://github.com/ppriyank/Pytorch-Additive_Margin_Softmax_for_Face_Verification/blob/master/AM_Softmax.py
		stats = F.normalize(stats, p = 2, dim = 1)
		with torch.no_grad():
			self.fc.weight.div_(torch.norm(self.fc.weight, dim = 1, keepdim=True))
		
		wf = self.fc(stats)

		if predict:
			return wf

		b = wf.size(0)

		for i in range(b):
			wf[i][labels[i]] = wf[i][labels[i]] - self.m
			
		weighted_wf = self.s * wf

		return weighted_wf

		
		


		


"""# Learning rate schedule
- For transformer architecture, the design of learning rate schedule is different from that of CNN.
- Previous works show that the warmup of learning rate is useful for training models with transformer architectures.
- The warmup schedule
  - Set learning rate to 0 in the beginning.
  - The learning rate increases linearly from 0 to initial learning rate during warmup period.
"""

import math

import torch
from torch.optim import Optimizer
from torch.optim.lr_scheduler import LambdaLR


def get_cosine_schedule_with_warmup(
	optimizer: Optimizer,
	num_warmup_steps: int,
	num_training_steps: int,
	num_cycles: float = 0.5,
	last_epoch: int = -1,
):
	"""
	Create a schedule with a learning rate that decreases following the values of the cosine function between the
	initial lr set in the optimizer to 0, after a warmup period during which it increases linearly between 0 and the
	initial lr set in the optimizer.
	Args:
		optimizer (:class:`~torch.optim.Optimizer`):
		The optimizer for which to schedule the learning rate.
		num_warmup_steps (:obj:`int`):
		The number of steps for the warmup phase.
		num_training_steps (:obj:`int`):
		The total number of training steps.
		num_cycles (:obj:`float`, `optional`, defaults to 0.5):
		The number of waves in the cosine schedule (the defaults is to just decrease from the max value to 0
		following a half-cosine).
		last_epoch (:obj:`int`, `optional`, defaults to -1):
		The index of the last epoch when resuming training.
	Return:
		:obj:`torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.
	"""
	def lr_lambda(current_step):
		# Warmup
		if current_step < num_warmup_steps:
			return float(current_step) / float(max(1, num_warmup_steps))
		# decadence
		progress = float(current_step - num_warmup_steps) / float(
			max(1, num_training_steps - num_warmup_steps)
		)
		return max(
			0.0, 0.5 * (1.0 + math.cos(math.pi * float(num_cycles) * 2.0 * progress))
		)

	return LambdaLR(optimizer, lr_lambda, last_epoch)

"""# Model Function
- Model forward function.
"""

import torch


def model_fn(batch, model, criterion, device):
	"""Forward a batch through the model."""

	mels, labels = batch
	mels = mels.to(device)
	labels = labels.to(device)

	outs = model(mels, labels = labels)

	loss = criterion(outs, labels)

	# Get the speaker id with highest probability.
	preds = outs.argmax(1)
	# Compute accuracy.
	accuracy = torch.mean((preds == labels).float())

	return loss, accuracy

"""# Validate
- Calculate accuracy of the validation set.
"""

from tqdm import tqdm
import torch


def valid(dataloader, model, criterion, device): 
	"""Validate on validation set."""

	model.eval()
	running_loss = 0.0
	running_accuracy = 0.0
	pbar = tqdm(total=len(dataloader.dataset), ncols=0, desc="Valid", unit=" uttr")

	for i, batch in enumerate(dataloader):
		with torch.no_grad():
			loss, accuracy = model_fn(batch, model, criterion, device)
			running_loss += loss.item()
			running_accuracy += accuracy.item()

		pbar.update(dataloader.batch_size)
		pbar.set_postfix(
			loss=f"{running_loss / (i+1):.2f}",
			accuracy=f"{running_accuracy / (i+1):.2f}",
		)

	pbar.close()
	model.train()

	return running_accuracy / len(dataloader)

"""# Main function"""

from tqdm import tqdm

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.utils.data import DataLoader, random_split


def train_parse_args():
	"""arguments"""
	config = {
		"data_dir": "./Dataset",
		"batch_size": 32,
		"n_workers": 8,
		"valid_steps": 2000,
		"warmup_steps": 1000,
		"save_steps": 10000,
		"total_steps": 200000,
		"model_config":{
            "config1":{
                "d_model":200,
                "num_heads":5,
				"ffn_dim":4096,
				"num_layers":3,
				"depthwise_conv_kernel_size":3,
				"dropout": 0.1,
				"s": 15.0,
				"m":1e-4
            },
            "config2":{
                "d_model":140,
                "num_heads":5,
				"ffn_dim":4096,
				"num_layers":3,
				"depthwise_conv_kernel_size":3,
				"dropout": 0.1,
				"s": 15.0,
				"m":1e-4
            },
            "config3":{
                "d_model":100,
                "num_heads":4,
				"ffn_dim":2048,
				"num_layers":5,
				"depthwise_conv_kernel_size":3,
				"dropout": 0.1,
				"s": 15.0,
				"m":1e-4
			
            },
        },
        "model_path": {
            "config1":"./model03_1.ckpt",
            "config2":"./model03_2.ckpt",
            "config3":"./model03_3.ckpt"},
	}

	return config

results_valid = {}


def main(
	data_dir,
	batch_size,
	n_workers,
	valid_steps,
	warmup_steps,
	total_steps,
	save_steps,
	model_path,
	model_config,
):

	for i in model_config:
		"""Main function."""
		device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
		print(f"[Info]: Use {device} now!")

		train_loader, valid_loader, speaker_num = get_dataloader(data_dir, batch_size, n_workers)
		train_iterator = iter(train_loader)
		print(f"[Info]: Finish loading data!",flush = True)

		model = Classifier(**model_config[i],n_spks=speaker_num).to(device)
		criterion = nn.CrossEntropyLoss()
		optimizer = AdamW(model.parameters(), lr=1e-4, weight_decay=1e-6)
		scheduler = get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps)
		print(f"[Info]: Finish creating model!",flush = True)

		best_accuracy = -1.0
		best_state_dict = None

		pbar = tqdm(total=valid_steps, ncols=0, desc="Train", unit=" step")

		for step in range(total_steps):
			# Get data
			try:
				batch = next(train_iterator)
			except StopIteration:
				train_iterator = iter(train_loader)
				batch = next(train_iterator)

			loss, accuracy = model_fn(batch, model, criterion, device)
			batch_loss = loss.item()
			batch_accuracy = accuracy.item()

			# Updata model
			loss.backward()
			optimizer.step()
			scheduler.step()
			optimizer.zero_grad()

			# Log
			pbar.update()
			pbar.set_postfix(
				loss=f"{batch_loss:.2f}",
				accuracy=f"{batch_accuracy:.2f}",
				step=step + 1,
			)

			# Do validation
			if (step + 1) % valid_steps == 0:
				pbar.close()

				valid_accuracy = valid(valid_loader, model, criterion, device)

				# keep the best model
				if valid_accuracy > best_accuracy:
					best_accuracy = valid_accuracy
					results_valid[i] = best_accuracy
					best_state_dict = model.state_dict()

				pbar = tqdm(total=valid_steps, ncols=0, desc="Train", unit=" step")

			# Save the best model so far.
			if (step + 1) % save_steps == 0 and best_state_dict is not None:
				torch.save(best_state_dict, model_path[i])
				pbar.write(f"Step {step + 1}, best model saved. (accuracy={best_accuracy:.4f})")

		pbar.close()


if __name__ == "__main__":
	main(**train_parse_args())




for key, value in results_valid.items():
	print(f'model {key}: accuracy = {value} %')


time_end = time.time()
time_c = time_end - time_start

minutes, seconds = divmod(time_c, 60)
hours, minutes = divmod(minutes, 60)
print("time: %02d:%02d:%02d"%(hours,minutes,seconds))


# model config1: accuracy = 0.8622881355932204 %
#  "config1":{
#                 "d_model":80,
#                 "num_heads":5,
# 				"ffn_dim":2048,
# 				"num_layers":3,
# 				"depthwise_conv_kernel_size":3,
# 				"dropout": 0.1,
# 				"s": 15.0,
# 				"m":1e-4

# model config3: accuracy = 0.8608757062146892 %
            # "config3":{
            #     "d_model":80,
            #     "num_heads":4,
			# 	"ffn_dim":2048,
			# 	"num_layers":5,
			# 	"depthwise_conv_kernel_size":3,
			# 	"dropout": 0.1,
			# 	"s": 15.0,
			# 	"m":1e-4

# model config1: accuracy = 0.9043079096045198 %
# "config1":{
#                 "d_model":120,
#                 "num_heads":5,
# 				"ffn_dim":2048,
# 				"num_layers":3,
# 				"depthwise_conv_kernel_size":3,
# 				"dropout": 0.1,
# 				"s": 15.0,
# 				"m":1e-4
#             },
# model config2: accuracy = 0.8961864406779662 %
#             "config2":{
#                 "d_model":100,
#                 "num_heads":5,
# 				"ffn_dim":4096,
# 				"num_layers":3,
# 				"depthwise_conv_kernel_size":3,
# 				"dropout": 0.1,
# 				"s": 15.0,
# 				"m":1e-4
#             },



# "config1":{
	# "d_model":200,
	# "num_heads":5,
	# "ffn_dim":4096,
	# "num_layers":3,
	# "depthwise_conv_kernel_size":3,
	# "dropout": 0.1,
	# "s": 15.0,
	# "m":1e-4
# },
# model config1: accuracy = 0.9367937853107344 %


# "config2":{
# 	"d_model":140,
# 	"num_heads":5,
# 	"ffn_dim":4096,
# 	"num_layers":3,
# 	"depthwise_conv_kernel_size":3,
# 	"dropout": 0.1,
# 	"s": 15.0,
# 	"m":1e-4
# },
# model config2: accuracy = 0.916843220338983 %

