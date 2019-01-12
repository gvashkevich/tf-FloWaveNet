import tensorflow as tf
import numpy as np
import os
from sklearn.model_selection import train_test_split
import multiprocessing

_buffer_size = 500
_pad = 0

class Dataset:
    def __init__(self,  metadata_filename, base_dir, hparams):
        self._hparams = hparams

        #Base directory of the project (to map files from different locations)
        self._base_dir = base_dir

        #Load metadata
        self._data_dir = os.path.dirname(metadata_filename)
        with open(metadata_filename, 'r') as f:
            self._metadata = [line.strip().split('|') for line in f]

        indices = np.arange(len(self._metadata))
        train_indices, test_indices = train_test_split(indices,
            test_size=hparams.test_size, random_state=hparams.split_random_state)

        self._train_meta = list(np.array(self._metadata)[train_indices])
        self._test_meta = list(np.array(self._metadata)[test_indices])
        
        n_cpu = multiprocessing.cpu_count()

        with tf.device('/cpu:0'):
            self._audio_filenames = tf.placeholder(tf.string, shape=[None], name='audio_filenames')
            self._mel_filenames = tf.placeholder(tf.string, shape=[None], name='mel_filenames')
            self._speaker_ids = tf.placeholder(tf.int32, shape=[None], name='speaker_ids')

            dataset = tf.data.Dataset.from_tensor_slices((self._audio_filenames, self._mel_filenames, self._speaker_ids)) 
            dataset = dataset.apply(tf.data.experimental.shuffle_and_repeat(buffer_size=_buffer_size, seed=self._hparams.shuffle_random_seed))
            dataset = dataset.batch(hparams.batch_size)
            dataset = dataset.map(self._load_batch, n_cpu)
            dataset = dataset.prefetch(hparams.num_gpus)

            self._train_iterator = dataset.make_initializable_iterator()
            self.inputs = []
            self.local_conditions = []
            self.speaker_ids = []
            for i in range(hparams.num_gpus):
                train_batch = self._train_iterator.get_next()
                self.inputs.append(train_batch[0])
                self.local_conditions.append(train_batch[1])
                self.speaker_ids.append(train_batch[2])
                   
            self._test_iterator = dataset.make_initializable_iterator()
            test_batch = self._test_iterator.get_next()
            self.eval_inputs = test_batch[0]
            self.eval_local_conditions = test_batch[1]
            self.eval_speaker_ids = test_batch[2]
                            

    def initialize(self, sess):
        # audio_filename, mel_filename, timesteps, speaker_id, text
        audio_filenames, mel_filenames, _, speaker_ids, _ = zip(*self._train_meta)

        sess.run(self._train_iterator.initializer, 
                feed_dict={
                    self._audio_filenames: audio_filenames, 
                    self._mel_filenames: mel_filenames,
                    self._speaker_ids: speaker_ids
                })

        audio_filenames, mel_filenames, _, speaker_ids, _ = zip(*self._test_meta)

        sess.run(self._test_iterator.initializer, 
                feed_dict={
                    self._audio_filenames: audio_filenames, 
                    self._mel_filenames: mel_filenames,
                    self._speaker_ids: speaker_ids
                })


    def _py_load_batch(self, audio_files, mel_files, speaker_ids, max_time_steps=None):
        batch = []
        for audio_file, mel_file, speaker_id in zip(audio_files, mel_files, speaker_ids):
            audio_file = audio_file.decode() 
            mel_file = mel_file.decode()

            sample = self._py_load_sample(audio_file, mel_file, speaker_id)
            batch.append(sample)

        prepared_batch = self._prepare_batch(batch, max_time_steps)
        return prepared_batch

    def _load_batch(self, audio_files, mel_files, speaker_ids):
        batch = tf.py_func(self._py_load_batch, [audio_files, mel_files, speaker_ids, self._hparams.max_time_steps], (tf.float32, tf.float32, tf.int32))

        batch[0].set_shape((None, None, 1))
        batch[1].set_shape((None, None, self._hparams.num_mels))
        batch[2].set_shape((None, ))
        return batch


    def _py_load_sample(self, audio_file, mel_file, speaker_id):
        input_data = np.load(os.path.join(self._base_dir, audio_file))
        local_condition_features = np.load(os.path.join(self._base_dir, mel_file))

        return input_data, local_condition_features, speaker_id

    
    def _prepare_batch(self, batch, max_time_steps=None):
        #Limit time steps to save GPU Memory usage
        if max_time_steps is None:
            input_lengths = [np.int32(len(x[0])) for x in batch]
            max_time_steps = min(input_lengths)
        #Adjust time resolution for upsampling
        batch = self._adjust_time_resolution(batch, max_time_steps)

        #time lengths
        input_lengths = [np.int32(len(x[0])) for x in batch]
        max_input_length = max(input_lengths)
        max_c_length = max([np.int32(len(x[1])) for x in batch])
        speaker_ids = np.array([x[2] for x in batch], dtype=np.int32)

        inputs = self._prepare_inputs([x[0] for x in batch], max_input_length)
        local_condition_features = self._prepare_local_conditions([x[1] for x in batch], max_c_length)

        return inputs, local_condition_features, speaker_ids

    def _prepare_inputs(self, inputs, maxlen):
        x_batch = np.stack([_pad_inputs(x.reshape(-1, 1), maxlen) for x in inputs]).astype(np.float32)
        return x_batch


    def _prepare_local_conditions(self, c_features, maxlen):
        c_batch = np.stack([_pad_inputs(x, maxlen, _pad=0) for x in c_features]).astype(np.float32)
        return c_batch


    def _adjust_time_resolution(self, batch, max_time_steps):
        '''Adjust time resolution between audio and local condition
        '''
        new_batch = []
        for b in batch:
            x, c, g = b
            self._assert_ready_for_upsample(x, c)
            if max_time_steps is not None:
                max_steps = _ensure_divisible(max_time_steps, self._hparams.hop_size, True)
                if len(x) > max_time_steps:
                    max_time_frames = max_steps // self._hparams.hop_size
                    start = np.random.randint(0, len(c) - max_time_frames)
                    time_start = start * self._hparams.hop_size
                    x = x[time_start: time_start + max_time_frames * self._hparams.hop_size]
                    c = c[start: start + max_time_frames, :]
                    self._assert_ready_for_upsample(x, c)

            new_batch.append((x, c, g))
        return new_batch

    def _assert_ready_for_upsample(self, x, c):
        assert len(x) % len(c) == 0 and len(x) // len(c) == self._hparams.hop_size

def _pad_inputs(x, maxlen, _pad=0):
    return np.pad(x, [(0, maxlen - len(x)), (0, 0)], mode='constant', constant_values=_pad)


def _ensure_divisible(length, divisible_by=256, lower=True):
    if length % divisible_by == 0:
        return length
    if lower:
        return length - length % divisible_by
    else:
        return length + (divisible_by - length % divisible_by)

