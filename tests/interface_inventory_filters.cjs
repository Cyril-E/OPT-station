// Real stock choices and combined state/brand/material predicates.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../openprinttag_app/static/inventory-filters.js'),'utf8'),{window});
const filters=window.OPT_INVENTORY_FILTERS;
const items=[
 {id:0,in_stock:true,usage_state:'stock',main:{brand_name:'Prusament',material_type:'PETG'}},
 {id:1,in_stock:true,usage_state:'in_service',main:{brand_name:'prusament',material_type:'PLA'}},
 {id:2,in_stock:false,completed_at:'2026-10-31',usage_state:'stock',main:{brand_name:'Other',material_type:'PETG'}},
 {id:3,in_stock:false,usage_state:'stock',main:{brand_name:'Removed',material_type:'TPU'}},
 {id:4,in_stock:true,usage_state:'stock',main:{}}];
const ids=(view='all',brands=[],materials=[])=>items.filter(x=>filters.matches(x,view,new Set(brands),new Set(materials))).map(x=>x.id);
assert.deepEqual(ids(),[0,1,2,4]);assert.deepEqual(ids('stock'),[0,4]);assert.deepEqual(ids('production'),[1]);assert.deepEqual(ids('completed'),[2]);
assert.deepEqual(ids('all',['prusament']),[0,1]);assert.deepEqual(ids('all',['prusament','other'],['petg']),[0,2]);
assert.deepEqual(ids('stock',['prusament'],['pla']),[]);assert.deepEqual(ids('stock',['']),[4]);
const available=items.filter(x=>x.in_stock||x.completed_at);
assert.equal(filters.values(available,'brand_name').length,3);
assert.equal(filters.values(available,'material_type').some(([,v])=>v==='TPU'),false);
assert.equal(filters.values(available,'brand_name').filter(([k])=>k==='prusament').length,1);
console.log('Inventory filters: combined views, multi-selects, unknowns, case variants and removed spools verified.');
