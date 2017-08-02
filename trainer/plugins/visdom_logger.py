""" Logging to Visdom server """
from   collections import defaultdict
import numpy as np
import visdom

from   .plugin import Plugin
from   .logger import Logger


class BaseVisdomLogger(Logger):
    ''' 
        The base class for logging output to Visdom. 

        ***THIS CLASS IS ABSTRACT AND MUST BE SUBCLASSED***

        Note that the Visdom server is designed to also handle a server architecture, 
        and therefore the Visdom server must be running at all times. The server can 
        be started with 
        $ python -m visdom.server
        and you probably want to run it from screen or tmux. 
    '''
    _viz = visdom.Visdom()

    @property
    def viz(self):
        return type(self)._viz

    def __init__(self, fields, interval=None, win=None, env=None, opts={}):
        super(BaseVisdomLogger, self).__init__(fields, interval)
        self.win = win
        self.env = env
        self.opts = opts

    def log(self, *args, **kwargs):
        raise NotImplementedError("log not implemented for BaseVisdomLogger, which is an abstract class.")

    def _viz_prototype(self, vis_fn):
        ''' Outputs a function which will log the arguments to Visdom in an appropriate way.

            Args:
                vis_fn: A function, such as self.vis.image
        '''
        def _viz_logger(*args, **kwargs):
            self.win = vis_fn(*args, 
                    win=self.win,
                    env=self.env,
                    opts=self.opts, 
                    **kwargs)
        return _viz_logger

    def _log_all(self, log_fields, prefix=None, suffix=None, require_dict=False):
        ''' Gathers the stats form self.trainer.stats and passes them into self.log, as a list '''
        results = []
        for field_idx, field in enumerate(self.fields):
            parent, stat = None, self.trainer.stats
            for f in field:
                parent, stat = stat, stat[f]
            results.append(stat)
        self.log(*results)

    def epoch(self, epoch_idx):
        super(BaseVisdomLogger, self).epoch(epoch_idx)
        self.viz.save()

class VisdomSaver(Plugin):
    ''' Serialize the state of the Visdom server to disk. 
        Unless you have a fancy schedule, where different are saved with different frequencies,
        you probably only need one of these. 
    '''

    def __init__(self, envs=None, interval=[(1, 'epoch')]):
        super(VisdomSaver, self).__init__(interval)
        self.envs = envs
        self.viz = visdom.Visdom()
        for _, name in interval:
            setattr(self, name, self.save)

    def register(self, trainer):
        self.trainer = trainer

    def save(self, *args, **kwargs):
        self.viz.save(self.envs)
    

class VisdomLogger(BaseVisdomLogger):
    '''
        A generic Visdom class that works with the majority of Visdom plot types.
    '''

    def __init__(self, plot_type, fields, interval=None, win=None, env=None, opts={}):
        '''
            Args:
                plot_type: The name of the plot type, in Visdom
                fields: The fields to log. May either be the name of some stat (e.g. ProgressMonitor)
                    will have `stat_name='progress'`, in which case all of the fields under 
                    `log_HOOK_fields` will be logged. Finer-grained control can be specified
                    by using individual fields such as `progress.percent`. 
                interval: A List of 2-tuples where each tuple contains (k, HOOK_TIME). 
                    k (int): The logger will be called every 'k' HOOK_TIMES
                    HOOK_TIME (string): The logger will be called at the given hook

            Examples:
                >>> # Image example
                >>> img_to_use = skimage.data.coffee().swapaxes(0,2).swapaxes(1,2)
                >>> image_plug = ConstantMonitor(img_to_use, "image")
                >>> image_logger   = VisdomLogger('image', ["image.data"], [(2, 'iteration')])

                >>> # Histogram example
                >>> hist_plug = ConstantMonitor(np.random.rand(10000), "random")
                >>> hist_logger = VisdomLogger('histogram', ["random.data"], [(2, 'iteration')], opts=dict(title='Random!', numbins=20))
        '''
        super(VisdomLogger, self).__init__(fields, interval, win, env, opts)
        self.plot_type = plot_type
        self.chart = getattr(self.viz, plot_type)
        self.viz_logger = self._viz_prototype(self.chart)

    def log(self, *args, **kwargs):
        self.viz_logger(*args, **kwargs)


class VisdomPlotLogger(BaseVisdomLogger):
    
    def __init__(self, plot_type, fields, interval=None, win=None, env=None, opts={}):
        '''
            Args:
                plot_type: {scatter, line}

            Examples:
                >>> train = Trainer(model, criterion, optimizer, dataset)
                >>> progress_m = ProgressMonitor()
                >>> scatter_logger = VisdomScatterLogger(["progress.samples_used", "progress.percent"], [(2, 'iteration')])
                >>> train.register_plugin(progress_m)
                >>> train.register_plugin(scatter_logger)
        '''
        super(VisdomPlotLogger, self).__init__(fields, interval, win, env, opts)
        valid_plot_types = {
            "scatter": self.viz.scatter, 
            "line": self.viz.line }

        # Set chart type
        if 'plot_type' in self.opts:
            if plot_type not in valid_plot_types.keys():
                raise ValueError("plot_type \'{}\' not found. Must be one of {}".format(
                    plot_type, valid_plot_types.keys()))
            self.chart = valid_plot_types[plot_type]
        else:
            self.chart = self.viz.scatter

    def log(self, *args, **kwargs):
        if self.win is not None:
            if len(args) != 2:
                raise ValueError("When logging to {}, must pass in x and y values (and optionally z).".format(
                    type(self)))
            x, y = args
            self.viz.updateTrace(
                X=np.array([x]),
                Y=np.array([y]),
                win=self.win,
                env=self.env,
                opts=self.opts)
        else:
            self.win = self.chart(
                X=np.array([args]),
                win=self.win,
                env=self.env,
                opts=self.opts)


class VisdomTextLogger(BaseVisdomLogger):
    '''
        Creates a text window in visdom and logs output to it. 
        The output can be formatted with fancy HTML, and it new output can 
            be set to 'append' or 'replace' mode.
    '''
    valid_update_types = ['REPLACE', 'APPEND']

    def __init__(self, fields, interval=None, win=None, env=None, opts={}, update_type=valid_update_types[0]):
        '''
            Args:
                fields: The fields to log. May either be the name of some stat (e.g. ProgressMonitor)
                    will have `stat_name='progress'`, in which case all of the fields under 
                    `log_HOOK_fields` will be logged. Finer-grained control can be specified
                    by using individual fields such as `progress.percent`. 
                interval: A List of 2-tuples where each tuple contains (k, HOOK_TIME). 
                    k (int): The logger will be called every 'k' HOOK_TIMES
                    HOOK_TIME (string): The logger will be called at the given hook
                update_type: One of {'REPLACE', 'APPEND'}. Default 'REPLACE'.

            Examples:
                >>> progress_m = ProgressMonitor()
                >>> logger = VisdomTextLogger(["progress"], [(2, 'iteration')])
                >>> train.register_plugin(progress_m)
                >>> train.register_plugin(logger)
        '''
        super(VisdomTextLogger, self).__init__(fields, interval, win, env, opts)
        self.text = ''

        if update_type not in self.valid_update_types:
            raise ValueError("update type '{}' not found. Must be one of {}".format(update_type, self.valid_update_types))
        self.update_type = update_type

        self.viz_logger = self._viz_prototype(self.viz.text)


    def log(self, msg, *args, **kwargs):
        text = msg
        if self.update_type == 'APPEND' and self.text:
            self.text = "<br>".join([self.text, text])
        else:
            self.text = text
        self.viz_logger([self.text])

    def _log_all(self, log_fields, prefix=None, suffix=None, require_dict=False):
        results = []
        for field_idx, field in enumerate(self.fields):
            parent, stat = None, self.trainer.stats
            for f in field:
                parent, stat = stat, stat[f]
            name, output = self._gather_outputs(field, log_fields,
                                                parent, stat, require_dict)
            if not output:
                continue
            self._align_output(field_idx, output)
            results.append((name, output))
        if not results:
            return
        output = self._join_results(results)
        if prefix is not None:
            self.log(prefix)
        self.log(output)
        if suffix is not None:
            self.log(suffix)
