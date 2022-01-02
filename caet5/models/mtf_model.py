import functools
import gin
import t5
from t5.models.mtf_model import MtfModel
from t5.models.mtf_model import _get_latest_checkpoint_from_dir, _operative_config_path
from mesh_tensorflow.transformer import utils
from mesh_tensorflow.transformer import utils as mtf_utils

from mesh_tensorflow_caet5.utils import eval_model_ll, infer_model_ll, train_model_ll
from caet5.data.utils import get_mixture_or_task_ll
from caet5.models.mesh_transformer import mesh_train_dataset_fn_ll, mesh_eval_dataset_fn_ll


@gin.configurable
class MtfModel_ll(MtfModel):
    def __init__(self, *mtfmodel_args, attribute_bit=False, unsupervised_attribute_transfer_metrics=True,
                 control_code_bool=False, group_by_attribute=False, **mtfmodel_kwargs):
        super().__init__(*mtfmodel_args, **mtfmodel_kwargs)
        self.attribute_bit = attribute_bit
        self.unsupervised_attribute_transfer_metrics = unsupervised_attribute_transfer_metrics
        self.control_code_bool = control_code_bool
        self.group_by_attribute = group_by_attribute

    def train(self, mixture_or_task_name, steps, init_checkpoint=None,
              split="train"):
        """Train the model on the given Mixture or Task.
        Args:
          mixture_or_task_name: str, the name of the Mixture or Task to train on.
            Must be pre-registered in the global `TaskRegistry` or
            `MixtureRegistry.`
          steps: int, the total number of steps to train for.
          init_checkpoint: a string, if not None then read in variables from this
            checkpoint path when initializing variables. Will only initialize
            variables that appear both in the current graph and the checkpoint.
        """
        vocabulary = get_mixture_or_task_ll(
            mixture_or_task_name).get_vocabulary()
        dataset_fn = functools.partial(
            mesh_train_dataset_fn_ll, mixture_or_task_name=mixture_or_task_name,
            batch_size=self.batch_size, ensemble_inputs=self._ensemble_inputs,
            group_by_attribute=self.group_by_attribute)

        # When fine-tuning, we first load the gin config of the pre-trained model. Yet here we might set gin parameters
        # with different values than the gin parameter values from the pre-trained gin config. e.g.
        # t5.data.preprocessors.unsupervised.preprocessors.

        if self.group_by_attribute:
            train_model_ll(self.estimator(vocabulary, init_checkpoint), vocabulary,
                           self._sequence_length, self.batch_size, dataset_fn,
                           steps, self._ensemble_inputs, dataset_split=split)
        else:
            utils.train_model(self.estimator(vocabulary, init_checkpoint), vocabulary,
                              self._sequence_length, self.batch_size, dataset_fn,
                              steps, self._ensemble_inputs, dataset_split=split)

    def eval(self, mixture_or_task_name, checkpoint_steps=None, summary_dir=None,
             split="validation"):
        """Evaluate the model on the given Mixture or Task.
        Args:
          mixture_or_task_name: str, the name of the Mixture or Task to evaluate on.
            Must be pre-registered in the global `TaskRegistry` or
            `MixtureRegistry.`
          checkpoint_steps: int, list of ints, or None. If an int or list of ints,
            evaluation will be run on the checkpoint files in `model_dir` whose
            global steps are closest to the global steps provided. If None, run eval
            continuously waiting for new checkpoints. If -1, get the latest
            checkpoint from the model directory.
          summary_dir: str, path to write TensorBoard events file summaries for
            eval. If None, use model_dir/eval_{split}.
          split: str, the split to evaluate on.
        """
        if checkpoint_steps == -1:
            checkpoint_steps = _get_latest_checkpoint_from_dir(self._model_dir)
        vocabulary = get_mixture_or_task_ll(
            mixture_or_task_name).get_vocabulary()
        dataset_fn = functools.partial(
            mesh_eval_dataset_fn_ll, mixture_or_task_name=mixture_or_task_name)
        with gin.unlock_config():
            gin.parse_config_file(_operative_config_path(self._model_dir))
        eval_model_ll(self.estimator(vocabulary), vocabulary,
                      self._sequence_length, self.batch_size, split,
                      self._model_dir, dataset_fn, summary_dir, checkpoint_steps, attribute_bit=self.attribute_bit,
                      unsupervised_attribute_transfer_metrics=self.unsupervised_attribute_transfer_metrics,
                      control_code_bool=self.control_code_bool)

    def predict(self, input_file, output_file, checkpoint_steps=-1,
                beam_size=1, temperature=1.0,
                sentencepiece_model_path=t5.data.DEFAULT_SPM_PATH):
        """Predicts targets from the given inputs.
        Args:
          input_file: str, path to a text file containing newline-separated input
            prompts to predict from.
          output_file: str, path prefix of output file to write predictions to. Note
            the checkpoint step will be appended to the given filename.
          checkpoint_steps: int, list of ints, or None. If an int or list of ints,
            inference will be run on the checkpoint files in `model_dir` whose
            global steps are closest to the global steps provided. If None, run
            inference continuously waiting for new checkpoints. If -1, get the
            latest checkpoint from the model directory.
          beam_size: int, a number >= 1 specifying the number of beams to use for
            beam search.
          temperature: float, a value between 0 and 1 (must be 0 if beam_size > 1)
            0.0 means argmax, 1.0 means sample according to predicted distribution.
          sentencepiece_model_path: str, path to the SentencePiece model file to use
            for decoding. Must match the one used during training.
        """
        # TODO(sharannarang) : It would be nice to have a function like
        # load_checkpoint that loads the model once and then call decode_from_file
        # multiple times without having to restore the checkpoint weights again.
        # This would be particularly useful in colab demo.

        if checkpoint_steps == -1:
            checkpoint_steps = _get_latest_checkpoint_from_dir(self._model_dir)

        with gin.unlock_config():
            gin.parse_config_file(_operative_config_path(self._model_dir))
            gin.bind_parameter("Bitransformer.decode.beam_size", beam_size)
            gin.bind_parameter("Bitransformer.decode.temperature", temperature)

        vocabulary = t5.data.SentencePieceVocabulary(sentencepiece_model_path)
        infer_model_ll(self.estimator(vocabulary), vocabulary,
                       self._sequence_length, self.batch_size,
                       self._model_type, self._model_dir, checkpoint_steps,
                       input_file, output_file)
