#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
 void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
 if (!lib) { puts(dlerror()); return 2; }
 const char *names[]={"cuInit","cudaDriverGetVersion","cuDriverGetVersion","cuGetProcAddress","cuGetProcAddress_v2","cuMemAlloc_v2","cuLaunchKernel"};
 int missing=0;
 for(int i=0;i<7;i++){ void *p=dlsym(lib,names[i]); printf("%s: %s\n",names[i],p?"present":"MISSING"); if(!p) missing++; }
 int (*version)(int*)=dlsym(lib,"cudaDriverGetVersion"); int v=0; if(version) { int ret=version(&v); printf("cudaDriverGetVersion: ret=%d version=%d\n",ret,v); }
 return missing?1:0;
}
