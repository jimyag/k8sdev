#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
 void *lib=dlopen(argv[1], RTLD_NOW|RTLD_LOCAL);
 if(!lib){puts(dlerror());return 2;}
 int (*init)(void)=dlsym(lib,"nvmlInit_v2");
 int (*count)(unsigned*)=dlsym(lib,"nvmlDeviceGetCount_v2");
 int (*get)(unsigned,void**)=dlsym(lib,"nvmlDeviceGetHandleByIndex_v2");
 int (*index)(void*,unsigned*)=dlsym(lib,"nvmlDeviceGetIndex");
 int (*minor)(void*,unsigned*)=dlsym(lib,"nvmlDeviceGetMinorNumber");
 int (*uuid)(void*,char*,unsigned)=dlsym(lib,"nvmlDeviceGetUUID");
 assert(init && count && get && index && minor && uuid);
 assert(init()==0); unsigned n=0; assert(count(&n)==0); printf("count=%u\n",n);
 int failed=0;
 for(unsigned i=0;i<n;i++) {
  void *h=NULL,*back=NULL; unsigned idx=999,m=999; char id[96];
  assert(get(i,&h)==0); assert(index(h,&idx)==0); assert(minor(h,&m)==0); assert(uuid(h,id,sizeof(id))==0);
  int ret=get(idx,&back);
  printf("enumerated=%u returned_index=%u minor=%u uuid=%s roundtrip_ret=%d same_handle=%d\n",i,idx,m,id,ret,h==back);
  if(idx!=i || ret || h!=back)failed=1;
 }
 return failed;
}
