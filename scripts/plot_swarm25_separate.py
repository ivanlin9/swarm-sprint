"""Read-only snapshot plots; mean uses only fully completed matched blocks."""
from pathlib import Path
import argparse
import math
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from peer_silencing.storage import unseal

ROOT=Path(__file__).resolve().parents[1]
COUNTS=[0,1,3,5,8,10]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exclude',type=int,nargs='*',default=[])
    args=parser.parse_args()
    if any(b not in range(1,6) for b in args.exclude):parser.error('Repetitions must be1–5')
    blocks=[b for b in range(1,6) if b not in args.exclude]
    if not blocks:parser.error('At least one repetition is required')
    cells={}
    for folder in ['swarm25-replicates-v1','swarm25-extension-v1']:
        for p in (ROOT/'runs/govsim'/folder).glob('block-*/*/outcome.json'):
            row=unseal(p)
            if row['block'] in blocks:cells[row['block'],row['recruiter_count']]=row
    complete=[b for b in blocks if all((b,c) in cells for c in COUNTS)]
    suffix=('-excluding-'+ '-'.join(map(str,sorted(set(args.exclude))))) if args.exclude else ''
    out=ROOT/'reports/govsim-swarm25-five-repetitions'/(f'separate-plots-{len(cells)}-episodes'+suffix)
    out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':12,'axes.spines.top':False,'axes.spines.right':False})
    for divisor,stem,title,ylabel in [
        (1,'total_tons','Total ordinary-agent catch vs recruiter count','Total actual catch (tons; 15 ordinary agents)'),
        (15,'average_tons','Average ordinary-agent catch vs recruiter count','Average actual catch (tons per ordinary agent)')]:
        fig,ax=plt.subplots(figsize=(9,5.5))
        for b in blocks:
            vals=[sum(cells[b,c]['ordinary_allocated'])/divisor if (b,c) in cells else math.nan for c in COUNTS]
            if all(math.isnan(v) for v in vals):continue
            ax.plot(COUNTS,vals,'o--',linewidth=1.3,alpha=.5,label=f'Repetition {b}'+(' (partial)' if b not in complete else ''))
        means=[statistics.mean(sum(cells[b,c]['ordinary_allocated'])/divisor for b in complete) for c in COUNTS]
        ax.plot(COUNTS,means,'o-',color='#152d45',linewidth=3,label=f'Mean of {len(complete)} complete repetitions',zorder=10)
        for c,v in zip(COUNTS,means):ax.annotate(f'{v:.2f}',(c,v),xytext=(0,10),textcoords='offset points',ha='center',fontsize=10)
        ax.set(title=title,xlabel='Number of recruiters (25-agent swarm)',ylabel=ylabel)
        ax.set_xticks(COUNTS);ax.set_ylim(bottom=0);ax.margins(y=.2);ax.grid(alpha=.17);ax.legend(fontsize=9,loc='upper left')
        note=(f'Repetition {", ".join(map(str,sorted(set(args.exclude))))} excluded post hoc. ' if args.exclude else '')
        fig.text(.5,.02,note+f'{len(cells)} episodes shown; ordinary agents only. No significance claim.',ha='center',fontsize=9)
        fig.tight_layout(rect=(0,.055,1,1))
        fig.savefig(out/f'{stem}.png',dpi=180,facecolor='white');fig.savefig(out/f'{stem}.svg',facecolor='white');plt.close(fig)
        print(stem,'means',means,'path',out/f'{stem}.png')

if __name__=='__main__':main()
