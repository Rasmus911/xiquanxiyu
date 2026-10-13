const {signingPlan:basePlan,verifyCandidates:baseVerify}=require('./desktop-045.cjs')
const {trust}=require('./operations-release.cjs')
const releaseVersion='0.5.0'
const releaseNotes=Object.freeze(['优化主登录页面','新增账号密码修改功能','新增搓澡师下单打印小票的功能','新增每天小票补打的功能'])
const targets=Object.freeze(['win10-x86','win10-x64','win11-x86','win11-x64'])
const signingPlan=options=>basePlan({...options,version:releaseVersion,trust})
const verifyCandidates=root=>baseVerify(root,releaseVersion)
module.exports={releaseVersion,releaseNotes,targets,trust,signingPlan,verifyCandidates}
if(require.main===module)(process.argv[2]==='verify-candidates'?verifyCandidates(process.argv[3]):signingPlan())
  .then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.message);process.exitCode=1})
