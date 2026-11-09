"""Offline plot of completed first repetition; never dispatches API requests."""
from pathlib import Path
import json
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/govsim/swarm25-replicates-v1'
OUT=ROOT/'reports/govsim-swarm25-replicates/first-repetition'
COUNTS=[0,1,3,5,8,10]

def main():
    rows=[]
    for c in COUNTS:
        envelope=json.loads((RUN/f'block-01/r{c}/outcome.json').read_text())
        from peer_silencing.storage import unseal
        rows.append(unseal(RUN/f'block-01/r{c}/outcome.json'))
    data=[r['ordinary_allocated'] for r in rows]
    assert all(len(a)==15 for a in data)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,5.5),gridspec_kw={'width_ratios':[1.25,1]})
    x=np.arange(len(COUNTS));bottom=np.zeros(len(x))
    groups=[('Took 10 tons','#93a6ba',lambda v:v==10),('Took exactly 18 tons','#168b88',lambda v:v==18),('Took more than 18 tons','#e58a32',lambda v:v>18)]
    for label,color,pred in groups:
        heights=np.array([sum(pred(v) for v in a) for a in data])
        axes[0].bar(x,heights,bottom=bottom,color=color,width=.65,label=label)
        for i,n in enumerate(heights):
            if n:axes[0].text(i,bottom[i]+n/2,str(n),ha='center',va='center',weight='bold',color='white' if color!='#e58a32' else '#222222')
        bottom+=heights
    axes[0].set(ylim=(0,16),ylabel='Number of ordinary agents (15 per episode)',title='How many agents changed their catch?')
    axes[0].set_yticks([0,5,10,15]);axes[0].legend(loc='upper left',bbox_to_anchor=(0,-.15),frameon=False,fontsize=10)
    means=[statistics.mean(a) for a in data]
    axes[1].bar(x,means,color=['#93a6ba']*3+['#e58a32','#168b88','#168b88'],width=.65)
    axes[1].axhline(10,color='#67768a',linestyle='--',linewidth=1)
    for i,v in enumerate(means):axes[1].text(i,v+.45,f'{v:.2f}',ha='center',fontsize=10)
    axes[1].annotate('One agent took 170 tons;\nthe other 14 took 10.',xy=(3,means[3]),xytext=(1.6,27),arrowprops={'arrowstyle':'->','color':'#aa5412'},fontsize=10,color='#8e4510',ha='center')
    axes[1].set(ylim=(0,32),ylabel='Mean actual allocated catch (tons)',title='Mean catch is sensitive to the outlier')
    for ax in axes:
        ax.set_xticks(x,COUNTS);ax.set_xlabel('Number of recruiters');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('First repetition: 25-agent swarms, ordinary-agent outcomes only',fontsize=15,weight='bold',y=.98)
    fig.text(.5,.025,'One episode per condition • Same 15 ordinary agents scored • All 10 potential recruiter slots excluded • No significance claim',ha='center',fontsize=9,color='#526174')
    fig.subplots_adjust(top=.84,bottom=.26,wspace=.3)
    OUT.mkdir(parents=True,exist_ok=True)
    fig.savefig(OUT/'first_repetition.png',dpi=200,facecolor='white')
    fig.savefig(OUT/'first_repetition.svg',facecolor='white')
    plt.close(fig)
    print(OUT/'first_repetition.png')

if __name__=='__main__':main()
