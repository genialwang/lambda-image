import os
from lambdaimage import lambdaimageContext
from lambdaimage.imgprocessing.deconvolution import Deconvolution
import time

input='/user/wb/deconv/'
output='/home/wb/data/standalone/'

def hdfs_in_out(input, output):
    in_list=[]
    out_list=[]
    #os.system("hdfs dfs -ls -R  "+input+" >hdfs_tmp.txt")
    os.system("hadoop dfs -lsr "+input+" >hdfs_tmp.txt")
    file=open('hdfs_tmp.txt')
    content=file.read()

    lines=content.split('\n')

    data=[]
    for i in lines:
        data.extend(i.split(" "))
    
    files=[]
    for i in range(len(data)):
        if( data[i].startswith('/')):
            files.append(data[i])
    
    directorys=[]
    for i in range(len(files)):
        directorys.append(os.path.dirname(files[i]))

    directorys=list(set(directorys))
    
    for i in range(len(directorys)):
        #in_list.append('hdfs://localhost:9000'+directorys[i]+'/*.tif')
        in_list.append('hdfs://10.18.129.12:9000'+directorys[i]+'/*.tif')
        #in_list.append('hdfs://blade12.ncic.cn:8020'+directorys[i]+'/*.tif')
    
    for i in range(len(directorys)):
        denoise=output+directorys[i][len(input):]
        out_list.append(denoise)
        if not os.path.exists(denoise):
            os.makedirs(denoise)
            #pass
    
    return (in_list, out_list)

if __name__=='__main__':
    inlist, outlist=hdfs_in_out(input, output) 
    print "inlist"
    print inlist
    print "outlist"
    print outlist

#    for i in range(len(inlist)):
#        print 'in: ', inlist[i]
#        print 'out: ', outlist[i]
    
    #tsc=lambdaimageContext.start(master="spark://blade12:7077", appName="deconv", pyFiles=['eggtest-0.1-py2.7.egg'])
    tsc=lambdaimageContext.start(appName="deconv")
    reg=Deconvolution('rl')
    iters=[200, 250]
    for iter in iters:
        reg.prepare("/home/wb/hdfs_2d/PSF_2d.tif", iter)
        for i in range(len(inlist)):
            try:
                imIn=tsc.loadImages(inlist[i], inputFormat='tif-stack')
                t_start=time.time()
                result=reg.run(imIn)
                result.exportAsTiffs(outlist[i], overwrite=True)
                t_end=time.time()
                print 'spark cluster image: ', inlist[i][len(input):], 'iter: ', iter, ' time: ', (t_end-t_start)
            except:
                print 'error ', inlist[i]
