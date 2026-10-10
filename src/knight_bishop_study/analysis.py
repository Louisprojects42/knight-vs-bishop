"""Analyze reduced SQLite records without fetching PGNs again."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np
from . import sampling as study



def group_keys(speed,band,length):
    return [(s,b,l) for s in ('all',speed) for b in ('all',band) for l in ('all',length)]


def write_csv(path,rows):
    if not rows:
        return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=keys)
        writer.writeheader();writer.writerows(rows)


def finite(value):
    return float(value) if np.isfinite(value) else None


def compare(matrix,weights,n_index,b_index,den_index,bden_index=None,factor=1):
    if bden_index is None:
        bden_index=den_index
    totals=matrix.sum(axis=0)
    n=totals[n_index]/totals[den_index]*factor if totals[den_index] else np.nan
    b=totals[b_index]/totals[bden_index]*factor if totals[bden_index] else np.nan
    sampled=weights@matrix
    with np.errstate(invalid='ignore',divide='ignore'):
        difference=(sampled[:,b_index]/sampled[:,bden_index]-sampled[:,n_index]/sampled[:,den_index])*factor
    valid=difference[np.isfinite(difference)]
    low,high=np.quantile(valid,[.025,.975]) if len(valid) else (np.nan,np.nan)
    return dict(knight=finite(n),bishop=finite(b),difference=finite(b-n),ci_low=finite(low),ci_high=finite(high))


def leader(effect,n,windows,minimum=200,lower_is_better=False):
    if n<minimum or windows<6 or effect['ci_low'] is None:
        return 'too_few_games'
    if effect['ci_low']>0:
        return 'knight' if lower_is_better else 'bishop'
    if effect['ci_high']<0:
        return 'bishop' if lower_is_better else 'knight'
    return 'inconclusive'


def logistic_fit(x,y,penalty=.5,max_iterations=60):
    """Ridge-regularized binomial likelihood, using analytic Newton steps."""
    beta=np.zeros(x.shape[1])
    penalties=np.full(x.shape[1],penalty);penalties[0]=0
    converged=False
    for iteration in range(max_iterations):
        eta=np.clip(x@beta,-35,35)
        probability=1/(1+np.exp(-eta))
        variance=probability*(1-probability)
        hessian=x.T@(variance[:,None]*x)+np.diag(penalties)
        gradient=x.T@(y-probability)-penalties*beta
        step=np.linalg.solve(hessian,gradient)
        old=np.logaddexp(0,x@beta).sum()-y@(x@beta)+.5*np.sum(penalties*beta**2)
        scale=1.
        while scale>1/1024:
            candidate=beta+scale*step
            eta_new=x@candidate
            objective=np.logaddexp(0,eta_new).sum()-y@eta_new+.5*np.sum(penalties*candidate**2)
            if objective<=old+1e-8:
                break
            scale/=2
        beta=candidate
        if np.max(np.abs(scale*step))<1e-7:
            converged=True
            break
    probability=1/(1+np.exp(-np.clip(x@beta,-35,35)))
    hessian=x.T@((probability*(1-probability))[:,None]*x)+np.diag(penalties)
    return beta,probability,hessian,dict(iterations=iteration+1,converged=converged,penalty=penalty)


SPEEDS=['blitz','bullet','rapid','classical','ultrabullet','unknown_or_correspondence']


def design(outcomes):
    months=sorted({row['month'] for row in outcomes})
    names=['intercept','bishop','white','rating_gap_100','side_to_move','pawns_8','rooks_2','queens','snapshot_ply_100',
           'passed_pawn_diff_4','pawn_island_diff_4','blocked_pawn_diff_4','central_pawn_diff_4','king_center_diff_4']
    names += ['band_'+b for b in study.BANDS[1:]]
    names += ['bishop_band_'+b for b in study.BANDS[1:]]
    names += ['speed_'+s for s in SPEEDS[1:]]
    names += ['month_'+m for m in months[1:]]
    features,target,clusters=[],[],[]
    for outcome in outcomes:
        for color in ('white','black'):
            opponent='black' if color=='white' else 'white'
            bishop=int(outcome['bishop_color']==color)
            own,opp=outcome[color+'_pawns'],outcome[opponent+'_pawns']
            row=[1,bishop,1 if color=='white' else -1,
                 (outcome[color+'_rating']-outcome[opponent+'_rating'])/100,
                 1 if outcome['side_to_move']==color else -1,
                 outcome['pawns']/8,outcome['rooks']/2,outcome['queens'],outcome['ply']/100]
            row += [(own[k]-opp[k])/4 for k in ('passed','islands','blocked','central_pawns','king_center')]
            row += [int(outcome['rating_band']==b) for b in study.BANDS[1:]]
            row += [bishop*int(outcome['rating_band']==b) for b in study.BANDS[1:]]
            row += [int(outcome['speed']==s) for s in SPEEDS[1:]]
            row += [int(outcome['month']==m) for m in months[1:]]
            features.append(row)
            target.append(int(outcome['result']==('1-0' if color=='white' else '0-1')))
            clusters.append(outcome['window_id'])
    return np.asarray(features,float),np.asarray(target,float),np.asarray(clusters),names


def bishop_versions(x):
    b=x.copy();n=x.copy()
    b[:,1]=1;n[:,1]=0
    # Main rating-band indicator columns 14:19, interaction columns 19:24.
    b[:,19:24]=x[:,14:19];n[:,19:24]=0
    return n,b


def outcome_analysis(outcomes,windows,weights):
    if len(outcomes)<200:
        raise ValueError('Too few balanced outcome positions for the model')
    x,y,clusters,names=design(outcomes)
    ordered=sorted(set(clusters),key=lambda s:study.stable_fraction('validation:'+s))
    test_windows=set(ordered[:max(1,len(ordered)//5)])
    test=np.array([c in test_windows for c in clusters])
    trained,_,_,training_info=logistic_fit(x[~test],y[~test])
    predicted=1/(1+np.exp(-np.clip(x[test]@trained,-35,35)))
    baseline=np.mean(y[~test])
    validation=dict(train_games=int((~test).sum()/2),held_out_games=int(test.sum()/2),
                    held_out_windows=sorted(test_windows),brier_score=float(np.mean((predicted-y[test])**2)),
                    baseline_brier=float(np.mean((baseline-y[test])**2)),
                    log_loss=float(np.mean(np.logaddexp(0,x[test]@trained)-y[test]*(x[test]@trained))),
                    baseline_log_loss=float(-np.mean(y[test]*np.log(baseline)+(1-y[test])*np.log(1-baseline))),
                    training=training_info)
    beta,p,hessian,fit_info=logistic_fit(x,y)
    scores=np.array([x[clusters==cluster].T@(y[clusters==cluster]-p[clusters==cluster]) for cluster in windows])
    inv=np.linalg.inv(hessian)
    correction=len(windows)/(len(windows)-1)*(len(x)-1)/(len(x)-x.shape[1])
    covariance=inv@(scores.T@scores)@inv*correction
    nx,bx=bishop_versions(x)
    pn=1/(1+np.exp(-np.clip(nx@beta,-35,35)))
    pb=1/(1+np.exp(-np.clip(bx@beta,-35,35)))
    gradients=pb[:,None]*(1-pb[:,None])*bx-pn[:,None]*(1-pn[:,None])*nx
    group_ids=defaultdict(list)
    raw_arrays=defaultdict(lambda:np.zeros((len(windows),3)))
    windex={w:i for i,w in enumerate(windows)}
    for i,outcome in enumerate(outcomes):
        bishop_win=int(outcome['result']==('1-0' if outcome['bishop_color']=='white' else '0-1'))
        knight_win=int(outcome['result']==('0-1' if outcome['bishop_color']=='white' else '1-0'))
        for key in group_keys(outcome['speed'],outcome['rating_band'],outcome['game_length']):
            group_ids[key].extend([2*i,2*i+1])
            raw_arrays[key][windex[outcome['window_id']]] += [1,knight_win,bishop_win]
    summaries=[]
    for key,indices in sorted(group_ids.items()):
        array=raw_arrays[key]
        count=int(array[:,0].sum());cluster_count=int(np.count_nonzero(array[:,0]))
        raw=compare(array,weights,1,2,0,factor=100)
        gradient=gradients[indices].mean(axis=0)
        effect=float(np.mean(pb[indices]-pn[indices])*100)
        se=float(np.sqrt(max(0,gradient@covariance@gradient))*100)
        adjusted=dict(knight=float(pn[indices].mean()*100),bishop=float(pb[indices].mean()*100),
                      difference=effect,ci_low=effect-1.96*se,ci_high=effect+1.96*se)
        summaries.append(dict(speed=key[0],rating_band=key[1],game_length=key[2],matched_games=count,windows=cluster_count,
                              knight_win_pct=raw['knight'],bishop_win_pct=raw['bishop'],
                              draw_pct=100-raw['knight']-raw['bishop'],raw_difference_pp=raw['difference'],
                              raw_ci_low=raw['ci_low'],raw_ci_high=raw['ci_high'],
                              adjusted_knight_win_pct=adjusted['knight'],adjusted_bishop_win_pct=adjusted['bishop'],
                              adjusted_difference_pp=effect,adjusted_ci_low=adjusted['ci_low'],adjusted_ci_high=adjusted['ci_high'],
                              adjusted_leader=leader(adjusted,count,cluster_count,minimum=200)))
    validation_bins=[]
    for low in np.arange(0,1,.1):
        selected=(predicted>=low)&(predicted<low+.1)
        if selected.any():
            validation_bins.append(dict(predicted_bin=f'{low:.1f}-{low+.1:.1f}',observations=int(selected.sum()),
                                        mean_prediction=float(predicted[selected].mean()),actual_win_rate=float(y[test][selected].mean())))
    model=dict(coefficients=dict(zip(names,map(float,beta))),covariance=covariance.tolist(),
               fit=fit_info,validation=validation,calibration=validation_bins,
               method='ridge binomial regression, target actual win (draw/loss=0), mirrored player rows; standardized bishop vs knight type contrast; covariance clustered by sampled archive window',
               controls='rating gap, colour, side to move, matched pawn/rook/queen counts, checkpoint ply, passed/blocked/central pawns, pawn islands, king centralisation, rating band, time control pool, month; bishop×rating interaction',
               caveat='Observational adjusted association; no causal identification. Final game length is not a predictor and length-stratified results are descriptive.')
    return summaries,model


def main(out=Path('results')):
    OUT=Path(out)
    started=time.monotonic()
    manifest=json.loads((OUT/'sampling_manifest.json').read_text(encoding='utf-8'))
    by_id={x['task']['id']:x['sha256'] for x in manifest['windows']}
    windows=sorted(by_id)
    wi={w:i for i,w in enumerate(windows)}
    rng=np.random.default_rng(20261009)
    weights=rng.multinomial(len(windows),np.full(len(windows),1/len(windows)),size=1000)
    general_arrays=defaultdict(lambda:np.zeros((len(windows),7)))
    qualified_arrays=defaultdict(lambda:np.zeros((len(windows),3)))
    general_ids=defaultdict(set);qualified_ids=defaultdict(set)
    move_ids=defaultdict(lambda:defaultdict(set))
    general_count=0;evaluation_count=0;observed_dates=set()
    general_handle=(OUT/'player_games.csv').open('w',encoding='utf-8',newline='')
    evaluation_handle=(OUT/'evaluated_player_games.csv').open('w',encoding='utf-8',newline='')
    general_writer=None;evaluation_writer=None
    month_counts=defaultdict(Counter)
    with sqlite3.connect(OUT/'study.sqlite') as db:
        db.executescript('PRAGMA cache_size=-131072; PRAGMA temp_store=MEMORY;')
        for general,annotated,text in db.execute('SELECT general_sample,has_eval,players FROM games'):
            pair=json.loads(text)
            month_counts[pair[0]['month']]['general_games']+=int(general)
            month_counts[pair[0]['month']]['annotated_games']+=int(annotated)
            for row in pair:
                keys=group_keys(row['speed'],row['rating_band'],row['game_length'])
                w=wi[row['window_id']]
                for piece in ('knight','bishop'):
                    if row[piece+'_eval_moves']:
                        for key in keys:
                            move_ids[key][piece].add(row['game_id'])
                if general:
                    if general_writer is None:
                        general_writer=csv.DictWriter(general_handle,fieldnames=list(row))
                        general_writer.writeheader()
                    general_writer.writerow(row)
                    general_count+=1
                    observed_dates.add(row['utc_date'])
                    values=[1]+[row[piece+'_'+metric] for metric in ('capture','influence','mobility') for piece in ('knight','bishop')]
                    for key in keys:
                        general_arrays[key][w]+=values
                        general_ids[key].add(row['game_id'])
                if row['eval_qualified']:
                    if evaluation_writer is None:
                        evaluation_writer=csv.DictWriter(evaluation_handle,fieldnames=list(row))
                        evaluation_writer.writeheader()
                    evaluation_writer.writerow(row)
                    evaluation_count+=1
                    for key in keys:
                        qualified_arrays[key][w]+=[1,row['knight_delta_pp'],row['bishop_delta_pp']]
                        qualified_ids[key].add(row['game_id'])
        # One row per window/piece/speed/rating/length, not all moves in RAM.
        move_groups=list(db.execute('''SELECT window_id,piece,speed,rating_band,game_length,COUNT(*),
            SUM(delta_pp),SUM(loss_pp),SUM(blunder_200cp),SUM(blunder_20pp),COUNT(DISTINCT game_id),
            SUM(clock_seconds IS NOT NULL) FROM moves GROUP BY window_id,piece,speed,rating_band,game_length'''))
        clock_rows=[]
        for row in db.execute('''SELECT piece,rating_band,time_control,speed,CAST(clock_seconds/5 AS INTEGER)*5 AS bucket,
            COUNT(*) AS eligible_moves,SUM(blunder_200cp),SUM(blunder_20pp),SUM(loss_pp),SUM(delta_pp),COUNT(DISTINCT game_id)
            FROM moves WHERE clock_seconds IS NOT NULL AND clock_seconds>=0
            GROUP BY piece,rating_band,time_control,speed,bucket'''):
            piece,band,tc,speed,bucket,n,cp,wp,loss,delta,games=row
            clock_rows.append(dict(piece=piece,rating_band=band,time_control=tc,speed=speed,
                                   clock_bucket_start=bucket,clock_bucket_end=bucket+5,eligible_moves=n,
                                   blunders_200cp=cp,blunders_20pp=wp,normalized_blunder_200cp=cp/n,
                                   normalized_blunder_20pp=wp/n,mean_loss_pp=loss/n,mean_delta_pp=delta/n,games=games))
    general_handle.close();evaluation_handle.close()
    write_csv(OUT/'clock_normalization.csv',clock_rows)
    capture_summary=[]
    for key,array in sorted(general_arrays.items()):
        games=len(general_ids[key]);cluster_count=int(np.count_nonzero(array[:,0]))
        row=dict(speed=key[0],rating_band=key[1],game_length=key[2],games=games,
                 player_games=int(array[:,0].sum()),windows=cluster_count)
        for metric,ni,bi,factor in (('capture',1,2,2),('influence',3,4,1),('mobility',5,6,1)):
            effect=compare(array,weights,ni,bi,0,factor=factor)
            row.update({metric+'_'+k:v for k,v in effect.items()})
            row[metric+'_leader']=leader(effect,games,cluster_count)
        capture_summary.append(row)
    # Ratios are computed with all eligible piece-move opportunities as denominator.
    move_arrays=defaultdict(lambda:np.zeros((len(windows),10)))
    for window,piece,speed,band,length,count,delta,loss,cp,wp,games,clocks in move_groups:
        offset=0 if piece=='knight' else 5
        for key in group_keys(speed,band,length):
            move_arrays[key][wi[window],offset:offset+5] += [count,delta,loss,cp,wp]
    evaluation_summary=[]
    for key,array in sorted(move_arrays.items()):
        total=array.sum(axis=0)
        cluster_count=int(np.count_nonzero(array[:,0]+array[:,5]))
        row=dict(speed=key[0],rating_band=key[1],game_length=key[2],windows=cluster_count,
                 knight_eligible_moves=int(total[0]),bishop_eligible_moves=int(total[5]),
                 knight_games=len(move_ids[key]['knight']),bishop_games=len(move_ids[key]['bishop']))
        for metric,ni,bi,factor,lower in (('delta_per_move_pp',1,6,1,False),('loss_per_move_pp',2,7,1,True),
                                        ('blunder_200cp_pct',3,8,100,True),('blunder_20pp_pct',4,9,100,True)):
            effect=compare(array,weights,ni,bi,0,5,factor)
            row.update({metric+'_'+k:v for k,v in effect.items()})
            row[metric+'_leader']=leader(effect,min(row['knight_games'],row['bishop_games']),cluster_count,minimum=200,lower_is_better=lower)
        qa=qualified_arrays[key]
        if qa[:,0].sum():
            effect=compare(qa,weights,1,2,0)
            row.update({'delta_per_piece_game_pp_'+k:v for k,v in effect.items()})
            row['qualified_player_games']=int(qa[:,0].sum())
            row['qualified_games']=len(qualified_ids[key])
        else:
            row['qualified_player_games']=0;row['qualified_games']=0
        evaluation_summary.append(row)
    print('Capture/evaluation summaries complete.',flush=True)
    outcome_path=OUT/'outcome_sampling_manifest.json'
    while '--wait-outcomes' in sys.argv and not outcome_path.exists():
        print('Waiting for the outcome preprocessing manifest...',flush=True)
        time.sleep(30)
    outcome_manifest=json.loads(outcome_path.read_text(encoding='utf-8'))
    assert len(outcome_manifest['windows'])==len(windows)
    assert all(by_id[x['task']['id']]==x['sha256'] for x in outcome_manifest['windows']), 'Range content changed between scans'
    print('Fitting actual-outcome model...',flush=True)
    with sqlite3.connect(OUT/'outcomes.sqlite') as db:
        outcomes=[json.loads(row[0]) for row in db.execute('SELECT data FROM outcomes ORDER BY game_id')]
    for outcome in outcomes:
        month_counts[outcome['month']]['outcome_matches']+=1
    outcome_summary,model=outcome_analysis(outcomes,windows,weights)
    write_csv(OUT/'matched_positions.csv',[dict(r,white_pawns=json.dumps(r['white_pawns']),black_pawns=json.dumps(r['black_pawns'])) for r in outcomes])
    write_csv(OUT/'captures_by_rating_speed_length.csv',capture_summary)
    write_csv(OUT/'winning_chance_by_rating_speed_length.csv',evaluation_summary)
    write_csv(OUT/'actual_outcomes_by_rating_speed_length.csv',outcome_summary)
    write_csv(OUT/'model_calibration.csv',model['calibration'])
    (OUT/'outcome_model.json').write_text(json.dumps(model,indent=2),encoding='utf-8')
    dates=sorted(observed_dates)
    info=dict(general_games=manifest['unique_counts']['general_sample_games'],
              general_player_games=general_count,annotated_games=manifest['unique_counts']['annotated_games'],
              evaluated_minor_moves=manifest['unique_counts']['evaluated_minor_moves'],
              evaluated_qualified_player_games=evaluation_count,matched_outcome_games=len(outcomes),
              sampled_dates=dates,sampled_date_count=len(dates),months=manifest['months'],windows=len(windows),
              source_archive_gb=manifest['source_archive_bytes']/1e9,
              total_range_download_gb=(manifest['raw_downloaded_bytes']+outcome_manifest['raw_downloaded_bytes'])/1e9,
              source_window_gb=manifest['raw_downloaded_bytes']/1e9,
              monthly_counts={m:dict(c) for m,c in sorted(month_counts.items())},
              rating_bands=study.BANDS,length_bands=study.LENGTHS,bootstrap_replicates=1000,
              uncertainty='Archive-window cluster bootstrap; outcome model sandwich covariance clustered by window',
              elapsed_analysis_seconds=round(time.monotonic()-started,2),
              versions=dict(python=sys.version.split()[0],numpy=np.__version__,chess=study.chess.__version__,zstandard=study.zstandard.__version__))
    output=dict(metadata=info,captures=capture_summary,evaluations=evaluation_summary,outcomes=outcome_summary,model_validation=model['validation'])
    (OUT/'results.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(info,indent=2),flush=True)
    print('OVERALL',json.dumps(dict(captures=next(x for x in capture_summary if (x['speed'],x['rating_band'],x['game_length'])==('all','all','all')),
                                     evaluations=next(x for x in evaluation_summary if (x['speed'],x['rating_band'],x['game_length'])==('all','all','all')),
                                     outcomes=next(x for x in outcome_summary if (x['speed'],x['rating_band'],x['game_length'])==('all','all','all'))),indent=2),flush=True)


if __name__=='__main__':
    main()
