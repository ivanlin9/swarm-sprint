from govsim_probe import analyse_bargaining as analysis
from govsim_probe import bargaining_corrected as corrected

if __name__=='__main__':
    analysis.b=corrected
    analysis.main()
