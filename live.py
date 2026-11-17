"""Live TI radar range-profile logging; no generated data or replay."""
import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
import numpy as np
import serial
from serial.tools import list_ports
from radar_decoder import Decoder
from radar_model import load_model, classify, plot

ROOT = Path(__file__).resolve().parent


def configure(cli, cfg):
    lines = [s.split('%')[0].strip() for s in cfg.read_text(encoding='utf-8-sig').splitlines()]
    with (ROOT/'cli_live_log.txt').open('w', encoding='utf-8') as log:
        for command in filter(None, lines):
            cli.reset_input_buffer()
            cli.write((command+'\n').encode())
            response = bytearray()
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                response.extend(cli.read(cli.in_waiting or 1))
                if any(s in response for s in [b'Done', b'Error', b'not recognized']):
                    break
            answer = response.decode(errors='replace')
            log.write(command+'\n'+answer+'\n'); log.flush()
            if b'Done' not in response or b'Error' in response or b'not recognized' in response:
                raise RuntimeError('Radar rejected or did not acknowledge: '+command+'\n'+answer)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-ports', action='store_true')
    p.add_argument('--cli', help='CLI/Application UART, e.g. COM3')
    p.add_argument('--data', help='DATA/Auxiliary UART, e.g. COM4')
    p.add_argument('--baud', type=int, default=921600)
    p.add_argument('--cfg', type=Path, default=ROOT/'road_profile.cfg')
    args=p.parse_args()
    if args.list_ports:
        for port in list_ports.comports(): print(port.device, '-', port.description)
        return
    if not args.cli or not args.data: p.error('Specify --cli COMx and --data COMy; use --list-ports to find them.')
    if args.cli.lower()==args.data.lower(): p.error('CLI and DATA ports must be different.')
    model=load_model(); meta=model[0]
    if hashlib.sha256(args.cfg.read_bytes()).hexdigest()!=meta['cfg_sha256']:
        p.error('Configuration does not match saved training samples. Use bundled road_profile.cfg.')
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    output=ROOT/'outputs'; output.mkdir(exist_ok=True)
    stem=output/('live_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    raw_path=stem.with_name(stem.name+'_raw').with_suffix('.csv')
    pred_path=stem.with_name(stem.name+'_predictions').with_suffix('.csv')
    info={'source':'live_serial', 'ground_truth':'unlabeled', 'cli':args.cli,'data':args.data,
          'baud':args.baud,'cfg_sha256':meta['cfg_sha256'],'feature_indices':meta['indices'],
          'feature_window_seconds':1,'note':'Experimental wet/ice sample matching; scores are not probabilities.'}
    stem.with_suffix('.metadata.json').write_text(json.dumps(info,indent=2))
    cli=data=None; rows=[]; history=deque(); failure=None; fig=None
    try:
        cli=serial.Serial(args.cli,115200,timeout=.1,write_timeout=2)
        data=serial.Serial(args.data,args.baud,timeout=.01)
        print('Sending the bundled radar configuration...')
        configure(cli,args.cfg)
        decoder=Decoder(meta['bins'])
        fig=plt.figure(figsize=(11,8)); fig.canvas.manager.set_window_title('LIVE radar — close to stop and save')
        fig.text(.1,.5,'Waiting for live range-profile data (TLV 2)...')
        plt.show(block=False)
        started=time.monotonic(); last_frame=started; last_plot=0; last_pred=0; first_frame=None
        with raw_path.open('w',newline='',encoding='utf-8') as rf, pred_path.open('w',newline='',encoding='utf-8') as pf:
            raw=csv.writer(rf)
            raw.writerow(['timestamp_utc','unix_time_s','frame','condition']+[f'bin_{i:03d}' for i in range(meta['bins'])]); rf.flush()
            fields=['time_s','frame','source','scenario_label','predicted_surface','separation_margin']+[f'bin_{b:03d}' for b in meta['indices']]+['distance_dry','distance_wet','distance_ice']
            writer=csv.DictWriter(pf,fieldnames=fields); writer.writeheader(); pf.flush()
            print('LIVE acquisition started. Close the plot or press Ctrl+C to stop.\nCSV:',pred_path)
            while plt.fignum_exists(fig.number):
                packets=decoder.feed(data.read(data.in_waiting or 1))
                for frame, profile in packets:
                    now=time.monotonic(); wall=time.time(); last_frame=now
                    if first_frame is None: first_frame=now
                    raw.writerow([datetime.fromtimestamp(wall,timezone.utc).isoformat(),wall,frame,'unlabeled',*profile.astype(int)])
                    history.append((now,profile[meta['indices']]))
                    while history and now-history[0][0]>1: history.popleft()
                    if now-first_frame>=1 and now-last_pred>=.2:
                        x=np.median([v for _,v in history],axis=0)
                        label,margin,dist=classify(x,model)
                        row=dict(time_s=round(now-started,6),frame=frame,source='live_serial',scenario_label='unlabeled',predicted_surface=label,separation_margin=margin,
                                 **{f'bin_{b:03d}':float(v) for b,v in zip(meta['indices'],x)},
                                 **{f'distance_{k}':float(v) for k,v in zip(['dry','wet','ice'],dist)})
                        rows.append(row); writer.writerow(row); pf.flush(); last_pred=now
                if packets: rf.flush()
                now=time.monotonic()
                if now-last_frame>10: raise RuntimeError(f'No valid TLV 2 range profile for 10 seconds. Check DATA port/baud and firmware. Malformed packets: {decoder.bad}')
                if rows and now-last_plot>=.5:
                    plot(fig,rows[-300:],len(rows[-300:]),'live')
                    fig.suptitle('LIVE radar | '+rows[-1]['predicted_surface'].upper()+'\nExperimental sample matching • ground truth unknown',fontsize=13)
                    fig.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
                    for ax in fig.axes: ax.set_xlim(max(0,rows[-1]['time_s']-60),max(1,rows[-1]['time_s']))
                    fig.canvas.draw_idle(); last_plot=now
                plt.pause(.01)
    except KeyboardInterrupt:
        print('\nStopped by user.')
    except Exception as exc:
        failure=exc
    finally:
        if cli is not None:
            try: cli.write(b'sensorStop\n')
            except serial.SerialException: pass
            cli.close()
        if data is not None: data.close()
        if rows:
            saved=Figure(figsize=(11,8)); FigureCanvasAgg(saved)
            plot(saved,rows,len(rows),'live')
            saved.suptitle('LIVE radar results — ground truth unknown\nExperimental sample matching • scores are not probabilities',fontsize=13)
            saved.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
            saved.savefig(stem.with_suffix('.png'),dpi=160)
            print('Saved full-session line plot:',stem.with_suffix('.png'))
        print('Output folder:',output)
        if fig is not None: plt.close(fig)
    if failure: raise SystemExit('LIVE ERROR: '+str(failure))

if __name__=='__main__': main()
