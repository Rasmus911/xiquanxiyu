package com.xiquan.mobileordering;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.OutputStream;
import java.util.concurrent.atomic.AtomicBoolean;

/** Save one authenticated export to a user-picked document; no storage permission. */
@CapacitorPlugin(name="InventoryExcel")
public class InventoryExcelPlugin extends Plugin {
    private static final int MAX_BYTES=10*1024*1024;
    private final AtomicBoolean choosing=new AtomicBoolean(false);

    @PluginMethod
    public void save(PluginCall call) {
        String encoded=call.getString("source_base64");
        if (encoded==null || encoded.length()>(MAX_BYTES+2)/3*4) {
            call.reject("Excel文件超过10MB或无效"); return;
        }
        try {
            byte[] bytes=Base64.decode(encoded,Base64.NO_WRAP);
            if(bytes.length<4 || bytes.length>MAX_BYTES || bytes[0]!='P' || bytes[1]!='K' || bytes[2]!=3 || bytes[3]!=4) {
                call.reject("导出内容不是有效Excel文件"); return;
            }
        } catch(IllegalArgumentException error) { call.reject("Excel编码无效"); return; }
        if(!choosing.compareAndSet(false,true)){call.reject("请先完成当前文件保存");return;}
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        intent.putExtra(Intent.EXTRA_TITLE,"溪泉库存盘点表.xlsx");
        try { startActivityForResult(call,intent,"documentChosen"); }
        catch(Exception error){choosing.set(false);call.reject("无法打开系统文件保存器");}
    }

    @ActivityCallback
    private void documentChosen(PluginCall call,ActivityResult result) {
        if(call==null){choosing.set(false);return;}
        if(result.getResultCode()!=Activity.RESULT_OK || result.getData()==null || result.getData().getData()==null){
            choosing.set(false);JSObject reply=new JSObject();reply.put("saved",false);reply.put("cancelled",true);call.resolve(reply);return;
        }
        Uri uri=result.getData().getData();
        // Content URI was returned by the user's picker, never provided by JavaScript.
        if(!"content".equals(uri.getScheme())){choosing.set(false);call.reject("请选择系统文件保存位置");return;}
        getBridge().execute(()->{
            try(OutputStream output=getContext().getContentResolver().openOutputStream(uri,"wt")){
                if(output==null)throw new IllegalStateException("文件保存位置不可写");
                byte[] bytes=Base64.decode(call.getString("source_base64"),Base64.NO_WRAP);
                output.write(bytes);output.flush();JSObject reply=new JSObject();reply.put("saved",true);call.resolve(reply);
            }catch(Exception error){call.reject("Excel文件未能保存，请重新导出并选择其他位置");}
            finally{choosing.set(false);}
        });
    }
}
