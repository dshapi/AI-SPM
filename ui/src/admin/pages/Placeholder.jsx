import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'

export default function Placeholder({ title, description }) {
  return (
    <PageContainer>
      <PageHeader title={title} subtitle={description} />
      <div className="bg-white border border-gray-200 border-dashed rounded-xl flex flex-col items-center justify-center h-72 gap-2">
        <p className="text-sm font-semibold text-gray-400">Coming soon</p>
        <p className="text-xs text-gray-300">This page is under construction</p>
      </div>
    </PageContainer>
  )
}
