import os
import threading
import time
import importlib
from xml.etree.ElementInclude import include
from modules import devices
from modules.paths import script_path
import signal
import threading

import modules.codeformer_model as codeformer
import modules.extras
import modules.face_restoration
import modules.gfpgan_model as gfpgan
import modules.img2img

import modules.lowvram
import modules.paths
import modules.scripts
import modules.sd_hijack
import modules.sd_models
import modules.shared as shared
import modules.txt2img

import modules.ui
from modules import devices
from modules import modelloader
from modules.paths import script_path
from modules.shared import cmd_opts

import argparse

modelloader.cleanup_models()
modules.sd_models.setup_model()
codeformer.setup_model(cmd_opts.codeformer_models_path)
gfpgan.setup_model(cmd_opts.gfpgan_models_path)
shared.face_restorers.append(modules.face_restoration.FaceRestoration())
modelloader.load_upscalers()
queue_lock = threading.Lock()


def wrap_queued_call(func):
    def f(*args, **kwargs):
        with queue_lock:
            res = func(*args, **kwargs)

        return res

    return f


def wrap_gradio_gpu_call(func, extra_outputs=None):
    def f(*args, **kwargs):
        devices.torch_gc()

        shared.state.sampling_step = 0
        shared.state.job_count = -1
        shared.state.job_no = 0
        shared.state.job_timestamp = shared.state.get_job_timestamp()
        shared.state.current_latent = None
        shared.state.current_image = None
        shared.state.current_image_sampling_step = 0
        shared.state.interrupted = False
        shared.state.textinfo = None

        with queue_lock:
            res = func(*args, **kwargs)

        shared.state.job = ""
        shared.state.job_count = 0

        devices.torch_gc()

        return res

    return modules.ui.wrap_gradio_call(f, extra_outputs=extra_outputs)


modules.scripts.load_scripts(os.path.join(script_path, "scripts"))

shared.sd_model = modules.sd_models.load_model()
shared.opts.onchange("sd_model_checkpoint", wrap_queued_call(lambda: modules.sd_models.reload_model_weights(shared.sd_model)))

def webui(mode='api|ui', dblog=False):
    if dblog:
        import modules.db_logger as db
        db.initDbConnection()
    # check if mode includes api
    if mode.find('api') != -1:
        import headless_server as hs
        hs.run_server()
    if mode.find('ui') != -1:
        while 1:

            demo = modules.ui.create_ui(wrap_gradio_gpu_call=wrap_gradio_gpu_call)
            
            demo.launch(
                share=cmd_opts.share,
                server_name="0.0.0.0" if cmd_opts.listen else None,
                server_port=cmd_opts.port,
                debug=cmd_opts.gradio_debug,
                auth=[tuple(cred.split(':')) for cred in cmd_opts.gradio_auth.strip('"').split(',')] if cmd_opts.gradio_auth else None,
                inbrowser=cmd_opts.autolaunch,
                prevent_thread_lock=True
            )

            while 1:
                time.sleep(0.5)
                if getattr(demo, 'do_restart', False):
                    time.sleep(0.5)
                    demo.close()
                    time.sleep(0.5)
                    break

            print('Reloading Custom Scripts')
            modules.scripts.reload_scripts(os.path.join(script_path, "scripts"))
            print('Reloading modules: modules.ui')
            importlib.reload(modules.ui)
            print('Restarting Gradio')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default='api|ui', help='api|ui|api|ui')
    parser.add_argument('--dblog', type=bool, default=False, help='True|False')
    args = parser.parse_args()
    webui(args.mode, args.dblog)
