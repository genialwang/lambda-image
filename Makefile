.PHONY:all clean test

all:
	python setup.py build_ext --inplace
clean:
	find ./lambdaimage/udf -name "*.so" -o -name "*.pyc" -o -name "*.pyx.md5" -o -name "*.pyd" | xargs rm -f
	find . -name "*.pyx" -exec ./script/rm_pyx_c_file.sh {} \;
	rm -rf build/ ./dist
	rm -rf lambdaimage.egg-info/
test:
	nosetests -w ./test  --verbosity 2 --nologcapture

