#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
 void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL); assert(lib);
 int (*v)(int*)=dlsym(lib,"cuDriverGetVersion"); assert(v);
 int version=0; assert(v(&version)==0 && version==12080); assert(v(NULL)==1);
 int (*old)(const char*,void**,int,unsigned long long)=dlsym(lib,"cuGetProcAddress"); assert(old);
 int (*modern)(const char*,void**,int,unsigned long long,int*)=dlsym(lib,"cuGetProcAddress_v2"); assert(modern);
 void *p=NULL; int status=-1;
 assert(modern("cuInit",&p,2000,0,&status)==0 && p && status==0);
 assert(((int(*)(unsigned int))p)(0)==0);
 assert(modern("cuMemAlloc",&p,3020,0,&status)==0 && !p && status==1);
 assert(old("cuMemAlloc",&p,3020,0)==500 && !p);
 assert(modern("cuInit",&p,1000,0,&status)==0 && !p && status==2);
 assert(modern("cuInit",NULL,2000,0,&status)==1);
 assert(modern(NULL,&p,2000,0,&status)==1);
 assert(modern("cuInit",&p,2000,3,&status)==1);
 assert(old("cuGetProcAddress",&p,11030,0)==0 && p==(void*)old);
 assert(old("cuGetProcAddress",&p,12000,0)==0 && p==(void*)modern);
 puts("PASS: version, initialization, ABI selection, missing API and invalid arguments");
}
