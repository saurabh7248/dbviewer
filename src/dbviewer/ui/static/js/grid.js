/* Tabulator result-grid lifecycle and multi-result tabs. */
window.DBGrid = (() => {
  let grid = null, dataSets = [];
  function show(results) {
    dataSets = results || [];
    const tabs = document.querySelector('#result-tabs'); tabs.replaceChildren();
    dataSets.forEach((result,index) => {
      const button=document.createElement('button'); button.className='result-tab'+(index===0?' active':''); button.textContent=`Result ${index+1} · ${result.row_count} rows`;
      button.onclick=()=>render(index); tabs.append(button);
    });
    if(dataSets.length) render(0); else { if(grid) grid.destroy(); grid=null; document.querySelector('#result-grid').replaceChildren(); }
  }
  function render(index) {
    document.querySelectorAll('.result-tab').forEach((b,i)=>b.classList.toggle('active',i===index));
    if(grid) grid.destroy();
    const result=dataSets[index], columns=(result.columns||[]).map(name=>({title:name,field:name,headerFilter:false,sorter:'string'}));
    const rows=(result.rows||[]).map(row=>Object.fromEntries(result.columns.map((name,i)=>[name,row[i]])));
    if(!columns.length){document.querySelector('#result-grid').innerHTML='<p class="muted">Statement completed; no rows returned.</p>';return;}
    grid=new Tabulator('#result-grid',{data:rows,columns,layout:'fitDataStretch',height:'420px',pagination:false,groupBy:[],groupHeader:(value,count)=>`${value} <span style="color:#91a0b5">(${count} rows)</span>`,movableColumns:true,placeholder:'No rows'});
    const group=document.querySelector('#group-columns');group.replaceChildren(...result.columns.map(name=>{const option=document.createElement('option');option.value=name;option.textContent=name;return option;}));
    document.querySelector('#grid-search').oninput=event=>grid?.setFilter((data)=>Object.values(data).some(value=>String(value??'').toLowerCase().includes(event.target.value.toLowerCase())));
    document.querySelector('#export-csv').onclick=()=>grid?.download('csv','dbviewer-results.csv');
    document.querySelector('#export-json').onclick=()=>grid?.download('json','dbviewer-results.json');
  }
  function setGroups(fields){if(grid) grid.setGroupBy(fields);}
  document.addEventListener('DOMContentLoaded',()=>document.querySelector('#group-columns').addEventListener('change',event=>setGroups(Array.from(event.target.selectedOptions,option=>option.value))));
  return {show,setGroups};
})();
