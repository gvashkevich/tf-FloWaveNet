import tensorflow as tf 
import numpy as np 


# Default hyperparameters
hparams = tf.contrib.training.HParams(
    num_gpus = 3, #Determines the number of gpus in use
    ps_device_type = 'GPU', # 'CPU'/'GPU'  Where gradients will sync

    #Audio
    num_mels = 80, #Number of mel-spectrogram channels and local conditioning dimensionality
    rescale = True, #Whether to rescale audio prior to preprocessing
    rescaling_max = 0.999, #Rescaling value

    #Mel spectrogram
    n_fft = 1024, #Extra window size is filled with 0 paddings to match this parameter
    hop_size = 256, #For 22050Hz, 275 ~= 12.5 ms
    win_size = 1024, #For 22050Hz, 1100 ~= 50 ms (If None, win_size = n_fft)
    sample_rate = 16000, #22050 Hz (corresponding to ljspeech dataset)


    #Mel and Linear spectrograms normalization/scaling and clipping
    signal_normalization = True,
    allow_clipping_in_normalization = True, #Only relevant if mel_normalization = True
    symmetric_mels = True, #Whether to scale the data to be symmetric around 0
    max_abs_value = 4., #max absolute value of data. If symmetric, data will be [-max, max] else [0, max] 
    normalize_spectr = True, #whether to rescale melspectrogram to [0, 1]

    #Contribution by @begeekmyfriend
	#Spectrogram Pre-Emphasis (Lfilter: Reduce spectrogram noise and helps model certitude levels. Also allows for better G&L phase reconstruction)
	preemphasize = False, #whether to apply filter
	preemphasis = 0.97, #filter coefficient.

    #Limits
    min_level_db = -100,
    ref_level_db = 20,
    fmin = 60, #Set this to 75 if your speaker is male! if female, 125 should help taking off noise. (To test depending on dataset)
    fmax = 7600,
    
    max_time_steps = 6400,

    split_random_state = 123,
    test_size = 30,
    batch_size = 3,


    causal = False,
    n_block = 8,
    n_flow = 6,
    n_layer = 2,
    affine = True,
    causality = False,
    tf_random_seed = 75
    )

def hparams_debug_string():
    values = hparams.values()
    hp = ['  %s: %s' % (name, values[name]) for name in sorted(values) if name != 'sentences']
    return 'Hyperparameters:\n' + '\n'.join(hp)